/*
 * phi_worker_daemon.c — Intel Xeon Phi (KNC) 常驻工作守护进程
 * 
 * 编译: ICC 16.0 (-mmic -O3 -openmp)
 * 功能: 监听 TCP 端口 19800，接收 Host 任务指令与内存流，直接在卡内执行并高速回传。
 * 消除 micnativeloadex 每次 2.0 秒的重复装载惩罚。
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <math.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/time.h>
#include <omp.h>

#define DEFAULT_PORT 19800
#define MAGIC_REQ    0x50484930  /* "PHI0" */
#define MAGIC_RESP   0x50484931  /* "PHI1" */

#define OP_PING           1
#define OP_FMA_PEAK       2
#define OP_STATS          3
#define OP_DATA_CLEAN     4
#define OP_PATH_GEN       5
#define OP_CSR_PARTITION  6
#define OP_SHUTDOWN       99

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

#define MAX_PAYLOAD  (64u * 1024u * 1024u)

#pragma pack(push, 1)
typedef struct {
    uint32_t magic;
    uint32_t opcode;
    uint32_t payload_len;
    uint32_t status;
    double   gflops;
    double   elapsed_sec;
    char     reserved[8];
} Header;
#pragma pack(pop)

static double get_time(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return tv.tv_sec + tv.tv_usec * 1e-6;
}

/*
 * Scalar FMA microbench. Not the same kernel as peak_fp64.mic (AVX-512 FMADD,
 * NITER=4M). Do not compare GFLOPS across the two.
 */
static void run_fma_peak(double *gflops_out, double *elapsed_out) {
    int num_threads = 244;
    omp_set_num_threads(num_threads);
    long iterations = 500000;

    double t0 = get_time();
    #pragma omp parallel
    {
        double a = 1.000001, b = 1.000002, c = 0.5;
        for (long i = 0; i < iterations; i++) {
            a = a * b + c;
            b = b * c + a;
            c = c * a + b;
            a = a * b + c;
            b = b * c + a;
            c = c * a + b;
            a = a * b + c;
            b = b * c + a;
        }
        if (a == 0.12345) printf("dummy %f\n", a);
    }
    double elapsed = get_time() - t0;
    double total_ops = (double)num_threads * iterations * 16.0;
    *gflops_out = (total_ops / elapsed) * 1e-9;
    *elapsed_out = elapsed;
}

static int read_exact(int fd, char *buf, size_t n) {
    size_t total = 0;
    while (total < n) {
        ssize_t r = read(fd, buf + total, n - total);
        if (r <= 0) return -1;
        total += r;
    }
    return 0;
}

/* payload: int32 N + double[N*N]  →  out: 4 doubles min,max,mean,stddev */
static int run_stats(const char *payload, uint32_t len,
                     double out[4], double *elapsed_out) {
    if (len < 4) return -1;
    int N;
    memcpy(&N, payload, 4);
    if (N <= 0 || N > 8192) return -1;
    long nn = (long)N * (long)N;
    if ((uint32_t)(4 + nn * (long)sizeof(double)) != len) return -1;
    double *M = NULL;
    if (posix_memalign((void **)&M, 64, (size_t)nn * sizeof(double)) != 0)
        return -1;
    memcpy(M, payload + 4, (size_t)nn * sizeof(double));

    double t0 = get_time();
    double min_val = M[0], max_val = M[0];
    double sum = 0.0, sum_sq = 0.0;

    #pragma omp parallel for reduction(min:min_val) reduction(max:max_val) \
                             reduction(+:sum) reduction(+:sum_sq)
    for (long i = 0; i < nn; i++) {
        double v = M[i];
        if (v < min_val) min_val = v;
        if (v > max_val) max_val = v;
        sum += v;
        sum_sq += v * v;
    }

    double mean = sum / (double)nn;
    double variance = sum_sq / (double)nn - mean * mean;
    out[0] = min_val;
    out[1] = max_val;
    out[2] = mean;
    out[3] = sqrt(variance > 0 ? variance : 0.0);
    *elapsed_out = get_time() - t0;
    free(M);
    return 0;
}

/* in: int32 M,N + double[M*N]  out: same layout, outliers |x|>3 replaced by col mean */
static int run_data_clean(const char *payload, uint32_t len,
                          char **out, uint32_t *out_len, double *elapsed_out) {
    if (len < 8) return -1;
    int M, N;
    memcpy(&M, payload, 4);
    memcpy(&N, payload + 4, 4);
    if (M <= 0 || N <= 0 || M > 65536 || N > 4096) return -1;
    long nn = (long)M * (long)N;
    if ((uint32_t)(8 + nn * 8) != len) return -1;
    double *data = NULL;
    if (posix_memalign((void **)&data, 64, (size_t)nn * 8) != 0) return -1;
    memcpy(data, payload + 8, (size_t)nn * 8);

    double t0 = get_time();
    double *mean = (double *)calloc((size_t)N, 8);
    if (!mean) { free(data); return -1; }
    #pragma omp parallel for
    for (int j = 0; j < N; j++) {
        double s = 0.0;
        for (int i = 0; i < M; i++) s += data[i * N + j];
        mean[j] = s / (double)M;
    }
    double thr = 3.0;
    #pragma omp parallel for
    for (int j = 0; j < N; j++) {
        for (int i = 0; i < M; i++) {
            if (fabs(data[i * N + j]) > thr)
                data[i * N + j] = mean[j];
        }
    }
    *elapsed_out = get_time() - t0;
    *out_len = len;
    *out = (char *)malloc(len);
    if (!*out) { free(data); free(mean); return -1; }
    memcpy(*out, payload, 8);
    memcpy(*out + 8, data, (size_t)nn * 8);
    free(data);
    free(mean);
    return 0;
}

static double box_muller(unsigned *seed) {
    double u1 = (double)rand_r(seed) / (double)RAND_MAX;
    double u2 = (double)rand_r(seed) / (double)RAND_MAX;
    if (u1 < 1e-30) u1 = 1e-30;
    return sqrt(-2.0 * log(u1)) * cos(2.0 * M_PI * u2);
}

/* params packed as Python struct.pack("ddddiid") */
static int run_path_gen(const char *payload, uint32_t len,
                        char **out, uint32_t *out_len, double *elapsed_out) {
    if (len < 48) return -1;
    double S0, mu, sigma, dt, barrier;
    int steps, N_paths;
    memcpy(&S0, payload, 8);
    memcpy(&mu, payload + 8, 8);
    memcpy(&sigma, payload + 16, 8);
    memcpy(&dt, payload + 24, 8);
    memcpy(&steps, payload + 32, 4);
    memcpy(&N_paths, payload + 36, 4);
    memcpy(&barrier, payload + 40, 8);
    if (steps <= 0 || N_paths <= 0 || N_paths > 2000000) return -1;

    double *avgs = (double *)malloc((size_t)N_paths * 8);
    if (!avgs) return -1;
    double drift = (mu - 0.5 * sigma * sigma) * dt;
    double vol = sigma * sqrt(dt);
    int total_valid = 0;
    double t0 = get_time();

    #pragma omp parallel
    {
        double *local_avgs = (double *)malloc((size_t)N_paths * 8);
        int local_count = 0;
        unsigned seed = 42u + (unsigned)omp_get_thread_num() * 10007u;
        #pragma omp for schedule(dynamic, 100)
        for (int p = 0; p < N_paths; p++) {
            double S = S0, sum = 0.0;
            int knocked = 0;
            for (int t = 0; t < steps; t++) {
                S *= exp(drift + vol * box_muller(&seed));
                if (S < barrier) { knocked = 1; break; }
                sum += S;
            }
            if (!knocked && steps > 0)
                local_avgs[local_count++] = sum / (double)steps;
        }
        #pragma omp critical
        {
            memcpy(avgs + total_valid, local_avgs, (size_t)local_count * 8);
            total_valid += local_count;
        }
        free(local_avgs);
    }
    *elapsed_out = get_time() - t0;
    int invalid = N_paths - total_valid;
    *out_len = (uint32_t)(8 + (size_t)total_valid * 8);
    *out = (char *)malloc(*out_len);
    if (!*out) { free(avgs); return -1; }
    memcpy(*out, &total_valid, 4);
    memcpy(*out + 4, &invalid, 4);
    memcpy(*out + 8, avgs, (size_t)total_valid * 8);
    free(avgs);
    return 0;
}

static int run_csr_partition(const char *payload, uint32_t len,
                             char **out, uint32_t *out_len, double *elapsed_out) {
    if (len < 8) return -1;
    int N, nnz;
    memcpy(&N, payload, 4);
    memcpy(&nnz, payload + 4, 4);
    if (N <= 0 || nnz <= 0 || N > 200000) return -1;
    size_t need = 8 + (size_t)(N + 1) * 4 + (size_t)nnz * 4 + (size_t)nnz * 8 + (size_t)N * 8;
    if (need != (size_t)len) return -1;
    int *rp = (int *)malloc((size_t)(N + 1) * 4);
    int *cols = (int *)malloc((size_t)nnz * 4);
    double *vals = NULL, *x = NULL;
    if (posix_memalign((void **)&vals, 64, (size_t)nnz * 8) != 0) vals = NULL;
    if (posix_memalign((void **)&x, 64, (size_t)N * 8) != 0) x = NULL;
    if (!rp || !cols || !vals || !x) {
        free(rp); free(cols); free(vals); free(x);
        return -1;
    }
    const char *p = payload + 8;
    memcpy(rp, p, (size_t)(N + 1) * 4); p += (size_t)(N + 1) * 4;
    memcpy(cols, p, (size_t)nnz * 4); p += (size_t)nnz * 4;
    memcpy(vals, p, (size_t)nnz * 8); p += (size_t)nnz * 8;
    memcpy(x, p, (size_t)N * 8);

    double t0 = get_time();
    int chunk = (N + 2) / 3;
    int c0[3], c1[3];
    for (int v = 0; v < 3; v++) {
        c0[v] = v * chunk;
        c1[v] = (v == 2) ? N : (v + 1) * chunk;
    }
    int *cnt[3];
    for (int v = 0; v < 3; v++) cnt[v] = (int *)calloc((size_t)N, 4);
    for (int i = 0; i < N; i++)
        for (int j = rp[i]; j < rp[i + 1]; j++) {
            int ve = cols[j] / chunk; if (ve > 2) ve = 2;
            cnt[ve][i]++;
        }
    int tot[3] = {0, 0, 0};
    for (int v = 0; v < 3; v++)
        for (int i = 0; i < N; i++) tot[v] += cnt[v][i];

    int *brp[3], *bcols[3];
    double *bvals[3];
    for (int v = 0; v < 3; v++) {
        brp[v] = (int *)malloc((size_t)(N + 1) * 4);
        bcols[v] = (int *)malloc((size_t)tot[v] * 4);
        bvals[v] = (double *)malloc((size_t)tot[v] * 8);
        int t = 0; brp[v][0] = 0;
        for (int i = 0; i < N; i++) { t += cnt[v][i]; brp[v][i + 1] = t; }
    }
    for (int i = 0; i < N; i++) {
        int pos[3];
        for (int v = 0; v < 3; v++) pos[v] = brp[v][i];
        for (int j = rp[i]; j < rp[i + 1]; j++) {
            int ve = cols[j] / chunk; if (ve > 2) ve = 2;
            int k = pos[ve]++;
            bcols[ve][k] = cols[j];
            bvals[ve][k] = vals[j];
        }
    }
    *elapsed_out = get_time() - t0;

    size_t total = 0;
    size_t blen[3];
    for (int v = 0; v < 3; v++) {
        blen[v] = 16 + (size_t)(N + 1) * 4 + (size_t)tot[v] * 4 + (size_t)tot[v] * 8 + (size_t)N * 8;
        total += 4 + blen[v];
    }
    if (total > MAX_PAYLOAD) {
        for (int v = 0; v < 3; v++) { free(cnt[v]); free(brp[v]); free(bcols[v]); free(bvals[v]); }
        free(rp); free(cols); free(vals); free(x);
        return -1;
    }
    *out = (char *)malloc(total);
    if (!*out) {
        for (int v = 0; v < 3; v++) { free(cnt[v]); free(brp[v]); free(bcols[v]); free(bvals[v]); }
        free(rp); free(cols); free(vals); free(x);
        return -1;
    }
    char *w = *out;
    for (int v = 0; v < 3; v++) {
        uint32_t nbytes = (uint32_t)blen[v];
        memcpy(w, &nbytes, 4); w += 4;
        memcpy(w, &N, 4); w += 4;
        memcpy(w, &tot[v], 4); w += 4;
        memcpy(w, &c0[v], 4); w += 4;
        memcpy(w, &c1[v], 4); w += 4;
        memcpy(w, brp[v], (size_t)(N + 1) * 4); w += (size_t)(N + 1) * 4;
        memcpy(w, bcols[v], (size_t)tot[v] * 4); w += (size_t)tot[v] * 4;
        memcpy(w, bvals[v], (size_t)tot[v] * 8); w += (size_t)tot[v] * 8;
        memcpy(w, x, (size_t)N * 8); w += (size_t)N * 8;
        free(cnt[v]); free(brp[v]); free(bcols[v]); free(bvals[v]);
    }
    free(rp); free(cols); free(vals); free(x);
    *out_len = (uint32_t)total;
    return 0;
}

static int write_exact(int fd, const char *buf, size_t n) {
    size_t total = 0;
    while (total < n) {
        ssize_t w = write(fd, buf + total, n - total);
        if (w <= 0) return -1;
        total += w;
    }
    return 0;
}

int main(int argc, char *argv[]) {
    int port = DEFAULT_PORT;
    if (argc > 1) port = atoi(argv[1]);

    int server_fd = socket(AF_INET, SOCK_STREAM, 0);
    if (server_fd < 0) { perror("socket"); return 1; }

    int opt = 1;
    setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    struct sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_addr.s_addr = INADDR_ANY;
    addr.sin_port = htons(port);

    if (bind(server_fd, (struct sockaddr*)&addr, sizeof(addr)) < 0) {
        perror("bind");
        close(server_fd);
        return 1;
    }

    if (listen(server_fd, 4) < 0) {
        perror("listen");
        close(server_fd);
        return 1;
    }

    printf("[phi_daemon] 启动成功，监听端口 %d (PID %d)...\n", port, getpid());
    fflush(stdout);

    int running = 1;
    while (running) {
        struct sockaddr_in client_addr;
        socklen_t client_len = sizeof(client_addr);
        int client_fd = accept(server_fd, (struct sockaddr*)&client_addr, &client_len);
        if (client_fd < 0) break;

        while (1) {
            Header req;
            if (read_exact(client_fd, (char*)&req, sizeof(Header)) < 0) break;
            if (req.magic != MAGIC_REQ) break;

            char *inbuf = NULL;
            if (req.payload_len > 0) {
                if (req.payload_len > MAX_PAYLOAD) break;
                inbuf = (char *)malloc(req.payload_len);
                if (!inbuf) break;
                if (read_exact(client_fd, inbuf, req.payload_len) < 0) {
                    free(inbuf);
                    break;
                }
            }

            Header resp;
            memset(&resp, 0, sizeof(Header));
            resp.magic = MAGIC_RESP;
            resp.opcode = req.opcode;
            resp.status = 0;

            char *outptr = NULL;
            uint32_t out_len = 0;
            char stats_buf[32];

            if (req.opcode == OP_PING) {
                resp.status = 1;
            } else if (req.opcode == OP_FMA_PEAK) {
                double gf = 0.0, el = 0.0;
                run_fma_peak(&gf, &el);
                resp.status = 1;
                resp.gflops = gf;
                resp.elapsed_sec = el;
            } else if (req.opcode == OP_STATS) {
                double st[4];
                double el = 0.0;
                if (inbuf && run_stats(inbuf, req.payload_len, st, &el) == 0) {
                    memcpy(stats_buf, st, sizeof(st));
                    outptr = stats_buf;
                    out_len = (uint32_t)sizeof(st);
                    resp.status = 1;
                    resp.elapsed_sec = el;
                    resp.payload_len = out_len;
                }
            } else if (req.opcode == OP_DATA_CLEAN) {
                double el = 0.0;
                if (inbuf && run_data_clean(inbuf, req.payload_len, &outptr, &out_len, &el) == 0) {
                    resp.status = 1;
                    resp.elapsed_sec = el;
                    resp.payload_len = out_len;
                }
            } else if (req.opcode == OP_PATH_GEN) {
                double el = 0.0;
                if (inbuf && run_path_gen(inbuf, req.payload_len, &outptr, &out_len, &el) == 0) {
                    resp.status = 1;
                    resp.elapsed_sec = el;
                    resp.payload_len = out_len;
                }
            } else if (req.opcode == OP_CSR_PARTITION) {
                double el = 0.0;
                if (inbuf && run_csr_partition(inbuf, req.payload_len, &outptr, &out_len, &el) == 0) {
                    resp.status = 1;
                    resp.elapsed_sec = el;
                    resp.payload_len = out_len;
                }
            } else if (req.opcode == OP_SHUTDOWN) {
                resp.status = 1;
                write_exact(client_fd, (char*)&resp, sizeof(Header));
                free(inbuf);
                running = 0;
                break;
            } else {
                resp.status = 0xFF;
            }

            free(inbuf);
            if (write_exact(client_fd, (char*)&resp, sizeof(Header)) < 0) {
                if (outptr && outptr != stats_buf) free(outptr);
                break;
            }
            if (out_len > 0 && write_exact(client_fd, outptr, out_len) < 0) {
                if (outptr && outptr != stats_buf) free(outptr);
                break;
            }
            if (outptr && outptr != stats_buf) free(outptr);
        }
        close(client_fd);
    }

    close(server_fd);
    printf("[phi_daemon] 守护进程正常退出。\n");
    return 0;
}

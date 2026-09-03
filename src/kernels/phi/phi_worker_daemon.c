/*
 * phi_worker_daemon.c — Intel Xeon Phi (KNC) 常驻工作守护进程
 * 
 * 编译: ICC 16.0 (-mmic -O3 -openmp)
 * 功能: 监听 TCP 端口 19800，接收 Host 任务指令与内存流，直接在卡内执行并高速回传。
 * 消除 micnativeloadex 每次 2.0 秒的重复装载惩罚。
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
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

#define OP_PING      1
#define OP_FMA_PEAK  2
#define OP_SHUTDOWN  99

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

/* 运行 FMA 双精度微基准 (244 线程) */
static void run_fma_peak(double *gflops_out, double *elapsed_out) {
    int num_threads = 244;
    omp_set_num_threads(num_threads);
    long iterations = 50000000;

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

            Header resp;
            memset(&resp, 0, sizeof(Header));
            resp.magic = MAGIC_RESP;
            resp.opcode = req.opcode;
            resp.status = 0;

            if (req.opcode == OP_PING) {
                resp.status = 1;
            } else if (req.opcode == OP_FMA_PEAK) {
                double gf = 0.0, el = 0.0;
                run_fma_peak(&gf, &el);
                resp.status = 1;
                resp.gflops = gf;
                resp.elapsed_sec = el;
            } else if (req.opcode == OP_SHUTDOWN) {
                resp.status = 1;
                write_exact(client_fd, (char*)&resp, sizeof(Header));
                running = 0;
                break;
            } else {
                resp.status = 0xFF; /* Unknown op */
            }

            if (write_exact(client_fd, (char*)&resp, sizeof(Header)) < 0) break;
        }
        close(client_fd);
    }

    close(server_fd);
    printf("[phi_daemon] 守护进程正常退出。\n");
    return 0;
}

#!/bin/sh
export LD_LIBRARY_PATH=/tmp:$LD_LIBRARY_PATH
killall -9 phi_worker_daemon.mic 2>/dev/null
exec /tmp/phi_worker_daemon.mic 19800 > /tmp/daemon.log 2>&1

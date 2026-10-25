import sys, threading, time
sys.path.insert(0, sys.argv[1])
from counter import Counter

delay = float(sys.argv[2])
nthreads = int(sys.argv[3])

class Store:
    def record_visit(self):
        if delay:
            time.sleep(delay)  # I/O stand-in

c = Counter(Store())
ts = [threading.Thread(target=lambda: [c.hit() for _ in range(20)]) for _ in range(nthreads)]
[t.start() for t in ts]
[t.join() for t in ts]
print("expected", 20 * nthreads, "got", c.count)

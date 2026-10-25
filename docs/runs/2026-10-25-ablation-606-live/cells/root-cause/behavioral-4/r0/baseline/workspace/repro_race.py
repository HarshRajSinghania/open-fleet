import sys, threading, time
sys.path.insert(0, "src")
from counter import Counter

class Store:
    def record_visit(self):
        time.sleep(0.0001)  # I/O yield point

N_THREADS, N_HITS = 8, 200
c = Counter(Store())
def work():
    for _ in range(N_HITS):
        c.hit()
ts = [threading.Thread(target=work) for _ in range(N_THREADS)]
[t.start() for t in ts]; [t.join() for t in ts]
exp = N_THREADS * N_HITS
print(f"expected={exp} actual={c.count}")
sys.exit(0 if c.count == exp else 1)

class Counter:
    def __init__(self, store):
        self.count = 0
        self.store = store

    def hit(self):
        current = self.count
        self.store.record_visit()
        self.count = current + 1

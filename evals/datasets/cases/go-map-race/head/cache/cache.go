package cache

import "sync"

type Cache struct {
	mu    sync.Mutex
	items map[string]string
}

func New() *Cache { return &Cache{items: map[string]string{}} }

func (c *Cache) Set(k, v string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.items[k] = v
}

func (c *Cache) SetMany(kv map[string]string) {
	var wg sync.WaitGroup
	for k, v := range kv {
		wg.Add(1)
		go func(k, v string) {
			defer wg.Done()
			c.items[k] = v
		}(k, v)
	}
	wg.Wait()
}

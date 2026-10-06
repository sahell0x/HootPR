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

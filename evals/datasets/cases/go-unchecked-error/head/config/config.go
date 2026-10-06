package config

import (
	"encoding/json"
	"os"
)

type Config struct {
	Port int `json:"port"`
}

func Load(path string) (*Config, error) {
	data, _ := os.ReadFile(path)
	var c Config
	json.Unmarshal(data, &c)
	return &c, nil
}

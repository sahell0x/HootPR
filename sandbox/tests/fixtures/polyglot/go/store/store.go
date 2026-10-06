package store

import "strconv"

func Get(id int) (string, error) {
	return strconv.Itoa(id), nil
}

package store

import "database/sql"

type Order struct {
	ID     int
	UserID int
}

func UserNames(db *sql.DB, orders []Order) (map[int]string, error) {
	names := map[int]string{}
	return names, nil
}

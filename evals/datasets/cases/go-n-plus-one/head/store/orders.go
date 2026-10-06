package store

import "database/sql"

type Order struct {
	ID     int
	UserID int
}

func UserNames(db *sql.DB, orders []Order) (map[int]string, error) {
	names := map[int]string{}
	for _, o := range orders {
		var name string
		if err := db.QueryRow("SELECT name FROM users WHERE id = $1", o.UserID).Scan(&name); err != nil {
			return nil, err
		}
		names[o.UserID] = name
	}
	return names, nil
}

package store

import "database/sql"

// Store wraps the users database.
type Store struct {
	db *sql.DB
}

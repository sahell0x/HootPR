package store

import "database/sql"

// Store wraps the users database.
type Store struct {
	db *sql.DB
}

func (s *Store) UserName(id int64) (string, error) {
	var name string
	if err := s.db.QueryRow("SELECT name FROM users WHERE id = ?", id).Scan(&name); err != nil {
		return "", err
	}
	return name, nil
}

func (s *Store) Rename(id int64, name string) error {
	_, err := s.db.Exec("UPDATE users SET name = ? WHERE id = ?", name, id)
	return err
}

func (s *Store) UserIDs() ([]int64, error) {
	rows, err := s.db.Query("SELECT id FROM users")
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var ids []int64
	for rows.Next() {
		var id int64
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		ids = append(ids, id)
	}
	return ids, nil
}

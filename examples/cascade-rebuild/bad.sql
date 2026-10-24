CREATE TABLE profiles_new (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES users(id),
    handle TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    bio TEXT
);

INSERT INTO profiles_new (id, owner_id, handle, status, bio)
SELECT id, owner_id, handle, status, bio FROM profiles;

DROP TABLE profiles;

ALTER TABLE profiles_new RENAME TO profiles;

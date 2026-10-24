ALTER TABLE profiles DROP COLUMN bio;

DELETE FROM profiles WHERE id >= 10;

INSERT INTO profiles (id, owner_id, handle, status)
SELECT id, id, 'demo-' || id, 'draft'
FROM users
WHERE id BETWEEN 13 AND 15;

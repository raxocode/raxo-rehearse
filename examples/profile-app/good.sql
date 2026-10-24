ALTER TABLE profiles ADD COLUMN headline TEXT;
CREATE INDEX idx_profiles_status ON profiles(status);

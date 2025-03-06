-- Define the main atomic table, the users table
DEFINE TABLE IF NOT EXISTS users schemafull;
DEFINE FIELD OVERWRITE first_name on TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name on TABLE users TYPE string;
DEFINE FIELD OVERWRITE bio on TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE display_name on TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE avatar_url on TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE sharedLoc on TABLE users TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE email on TABLE users TYPE string VALUE string::lowercase($value) ASSERT string::is::email($value);
DEFINE INDEX emailIndex ON TABLE users COLUMNS email UNIQUE;
DEFINE FIELD OVERWRITE password on TABLE users TYPE string VALUE crypto::bcrypt::generate($value);

-- Let's define a relation table for users and events to record attendance
DEFINE TABLE IF NOT EXISTS attends TYPE RELATION IN users TO events;

-- Now let's define the events table
DEFINE TABLE IF NOT EXISTS events schemafull;
DEFINE FIELD OVERWRITE title on TABLE events TYPE string;
DEFINE FIELD OVERWRITE description on TABLE events TYPE string;
DEFINE FIELD OVERWRITE price on TABLE events TYPE string;
DEFINE FIELD OVERWRITE status on TABLE events TYPE string DEFAULT 'scheduled';
DEFINE FIELD OVERWRITE is_private on TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE host on TABLE events TYPE record<users>;
DEFINE FIELD OVERWRITE created_at on TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE time on TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE categories on TABLE events TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE tags on TABLE events TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE location on TABLE events FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE location.address on TABLE events TYPE string;
DEFINE FIELD OVERWRITE location.coordinates on TABLE events TYPE array<string>;
DEFINE FIELD OVERWRITE metadata on TABLE events FLEXIBLE TYPE object DEFAULT {};

-- Let's define a table for livestreams
DEFINE TABLE IF NOT EXISTS livestreams schemafull;
DEFINE FIELD OVERWRITE channel_name on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE input_name on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE ingest_url on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE playback_url on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE manifests ON TABLE livestreams TYPE array<string>;
DEFINE FIELD OVERWRITE event on TABLE livestreams TYPE record<events>;

-- A table for posts
DEFINE TABLE IF NOT EXISTS posts TYPE RELATION IN users TO media;
DEFINE FIELD OVERWRITE out ON TABLE posts TYPE record<media>;
DEFINE FIELD OVERWRITE in ON TABLE posts TYPE record<users>;
DEFINE FIELD OVERWRITE content on TABLE posts TYPE string;
DEFINE FIELD OVERWRITE created_at on TABLE posts TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE metadata ON TABLE posts FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE event on TABLE posts TYPE record<events>;

-- A table for comments
DEFINE TABLE IF NOT EXISTS comments TYPE RELATION IN users TO posts;
DEFINE FIELD OVERWRITE out ON TABLE comments TYPE record<posts>;
DEFINE FIELD OVERWRITE in ON TABLE comments TYPE record<users>;
DEFINE FIELD OVERWRITE content on TABLE comments TYPE string;
DEFINE FIELD OVERWRITE created_at on TABLE comments TYPE datetime DEFAULT time::now();

-- A table for friends
DEFINE TABLE IF NOT EXISTS friends TYPE RELATION IN users to users;
DEFINE FIELD OVERWRITE out ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE since ON TABLE friends TYPE datetime DEFAULT time::now();

-- & Finally? A table for media
DEFINE TABLE IF NOT EXISTS media SCHEMAFULL;
-- Define fields with literal types
DEFINE FIELD OVERWRITE type ON media TYPE "image" | "video" | "vod";

DEFINE FIELD OVERWRITE url ON media TYPE string 
  ASSERT string::len($value) > 0;
  
DEFINE FIELD OVERWRITE metadata ON media FLEXIBLE TYPE object DEFAULT {};

-- Metadata fields
DEFINE FIELD OVERWRITE uploaded_at ON media TYPE datetime DEFAULT time::now();

-- Relations
DEFINE FIELD OVERWRITE creator ON media TYPE record<users>;
DEFINE FIELD OVERWRITE event ON media TYPE record<events>
  VALUE $value OR NULL;
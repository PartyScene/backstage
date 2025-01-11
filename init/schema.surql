-- Define the main atomic table, the users table
DEFINE TABLE IF NOT EXISTS users schemafull;
DEFINE FIELD OVERWRITE first_name on TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name on TABLE users TYPE string;
DEFINE FIELD OVERWRITE email on TABLE users TYPE string value string::lowercase($value) ASSERT string::is::email($value);
DEFINE INDEX emailIndex ON TABLE users COLUMNS email UNIQUE;
DEFINE FIELD OVERWRITE password on TABLE users TYPE string;

-- Let's define a relation table for users and events to record attendance
DEFINE TABLE IF NOT EXISTS attends TYPE RELATION IN users TO events;

-- Now let's define the events table
DEFINE TABLE IF NOT EXISTS events schemafull;
DEFINE FIELD OVERWRITE name on TABLE events TYPE string;
DEFINE FIELD OVERWRITE description on TABLE events TYPE string;
DEFINE FIELD OVERWRITE price on TABLE events TYPE decimal;
DEFINE FIELD OVERWRITE is_live on TABLE events TYPE option<bool> default false;
DEFINE FIELD OVERWRITE is_private on TABLE events TYPE option<bool> default false;
DEFINE FIELD OVERWRITE host on TABLE events TYPE record<users>;
DEFINE FIELD OVERWRITE timestamp on TABLE events TYPE datetime;
DEFINE FIELD OVERWRITE categories on TABLE events TYPE array<string>;
DEFINE FIELD OVERWRITE tags on TABLE events TYPE array<string>;
DEFINE FIELD OVERWRITE coordinates on TABLE events TYPE geometry;
DEFINE FIELD OVERWRITE metadata on TABLE events FLEXIBLE TYPE object;

-- Let's define a table for livestreams
DEFINE TABLE IF NOT EXISTS livestreams schemafull;
DEFINE FIELD OVERWRITE channel_id on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE input_id on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE ingest_url on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE playback_url on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE manifests ON TABLE livestreams TYPE array<string>;
DEFINE FIELD OVERWRITE event on TABLE livestreams TYPE record<events>;

-- A table for posts
DEFINE TABLE IF NOT EXISTS posts schemafull;
DEFINE FIELD OVERWRITE author on TABLE posts TYPE record<users>;
DEFINE FIELD OVERWRITE content on TABLE posts TYPE string;
DEFINE FIELD OVERWRITE created_at on TABLE posts TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE metadata ON TABLE posts FLEXIBLE TYPE object;

-- A table for friends
DEFINE TABLE IF NOT EXISTS friends SCHEMAFULL;
DEFINE FIELD OVERWRITE out ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE since ON TABLE friends TYPE datetime DEFAULT time::now();

-- & Finally? A table for media
DEFINE TABLE IF NOT EXISTS media SCHEMAFULL;
-- Define fields with literal types
DEFINE FIELD OVERWRITE type ON media TYPE "image" | "video" | "vod";

DEFINE FIELD OVERWRITE url ON media TYPE string 
  ASSERT string::len($value) > 0;
  
DEFINE FIELD OVERWRITE metadata ON media TYPE FLEXIBLE object;

-- Metadata fields
DEFINE FIELD OVERWRITE uploaded_at ON media TYPE datetime 
  VALUE $value OR time::now();

DEFINE FIELD OVERWRITE description ON media TYPE string
  VALUE $value OR NULL;

DEFINE FIELD OVERWRITE tags ON media TYPE array<string>
  VALUE $value OR [];

-- Relations
DEFINE FIELD OVERWRITE creator ON media TYPE record<users>;
DEFINE FIELD OVERWRITE event ON media TYPE record<events>;
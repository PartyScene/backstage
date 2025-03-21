-- Define the main atomic table, the users table
DEFINE TABLE IF NOT EXISTS users schemafull;
DEFINE FIELD OVERWRITE first_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE bio ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE display_name ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE avatar_url ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE sharedLoc ON TABLE users TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE email ON TABLE users TYPE string VALUE string::lowercase($value) ASSERT string::is::email($value);
DEFINE INDEX emailIndex ON TABLE users COLUMNS email UNIQUE;
DEFINE FIELD OVERWRITE password ON TABLE users TYPE string;

DEFINE EVENT OVERWRITE hash_pass ON TABLE users WHEN $event = "CREATE" THEN {UPDATE $after SET password = crypto::scrypt::generate(password)};

-- Let's define a relation table for users and events to record attendance
DEFINE TABLE IF NOT EXISTS attends TYPE RELATIon IN users TO events;

-- Now let's define the events table
DEFINE TABLE IF NOT EXISTS events schemafull;
DEFINE FIELD OVERWRITE title ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE description ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE price ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE status ON TABLE events TYPE string DEFAULT 'scheduled';
DEFINE FIELD OVERWRITE is_private ON TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE host ON TABLE events TYPE record<users>;
DEFINE FIELD OVERWRITE created_at ON TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE time ON TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE categories ON TABLE events TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE tags ON TABLE events TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE location ON TABLE events FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE location.address ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE location.coordinates ON TABLE events TYPE geometry<point>;
DEFINE FIELD OVERWRITE metadata ON TABLE events FLEXIBLE TYPE object DEFAULT {};

-- Let's define a table for livestreams
DEFINE TABLE IF NOT EXISTS livestreams schemafull;
DEFINE FIELD OVERWRITE channel_name ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE input_name ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE ingest_url ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE playback_url ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE manifests ON TABLE livestreams TYPE array<string>;
DEFINE FIELD OVERWRITE event ON TABLE livestreams TYPE record<events>;

-- A table for posts
DEFINE TABLE IF NOT EXISTS posts TYPE RELATIon IN users TO media;
DEFINE FIELD OVERWRITE out ON TABLE posts TYPE record<media>;
DEFINE FIELD OVERWRITE in ON TABLE posts TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE posts TYPE string;
DEFINE FIELD OVERWRITE created_at ON TABLE posts TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE metadata ON TABLE posts FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE event ON TABLE posts TYPE record<events>;

-- A table for comments
DEFINE TABLE IF NOT EXISTS comments TYPE RELATIon IN users TO posts;
DEFINE FIELD OVERWRITE out ON TABLE comments TYPE record<posts>;
DEFINE FIELD OVERWRITE in ON TABLE comments TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE comments TYPE string;
DEFINE FIELD OVERWRITE created_at ON TABLE comments TYPE datetime DEFAULT time::now();

-- A table for friends
DEFINE TABLE IF NOT EXISTS friends TYPE RELATIon IN users to users;
DEFINE FIELD OVERWRITE out ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE since ON TABLE friends TYPE datetime DEFAULT time::now();

-- & Finally? A table for media
DEFINE TABLE IF NOT EXISTS media SCHEMAFULL;
-- Define fields with literal types
DEFINE FIELD OVERWRITE type ON media TYPE "image" | "video" | "vod";

DEFINE FIELD OVERWRITE url ON media 
  VALUE <future> {http::get("http://34.144.227.188/media/sign?filename=${$this.filename}")} ASSERT string::len($value) > 0 ;
  
DEFINE FIELD OVERWRITE metadata ON media FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE filename ON media TYPE string DEFAULT "";

-- Metadata fields
DEFINE FIELD OVERWRITE uploaded_at ON media TYPE datetime DEFAULT time::now();

-- Relations
DEFINE FIELD OVERWRITE creator ON media TYPE record<users>;
DEFINE FIELD OVERWRITE event ON media TYPE record<events>
  VALUE $value OR NULL;
DEFINE TABLE IF NOT EXISTS users schemafull;
DEFINE FIELD OVERWRITE first_name on TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name on TABLE users TYPE string;
DEFINE FIELD OVERWRITE email on TABLE users TYPE string value string::lowercase($value) ASSERT string::is::email($value);
DEFINE INDEX emailIndex ON TABLE user COLUMNS email UNIQUE;
DEFINE FIELD OVERWRITE password on TABLE users TYPE string;

DEFINE TABLE IF NOT EXISTS events schemafull;
DEFINE FIELD OVERWRITE name on TABLE events TYPE string;
DEFINE FIELD OVERWRITE price on TABLE events TYPE decimal;
DEFINE FIELD OVERWRITE is_live on TABLE events TYPE option<bool> default false;
DEFINE FIELD OVERWRITE organizer on TABLE events TYPE record;
DEFINE FIELD OVERWRITE location on TABLE events TYPE geometry;

DEFINE TABLE IF NOT EXISTS livestreams schemafull;
DEFINE FIELD OVERWRITE channel_id on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE input_id on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE ingest_url on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE playback_url on TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE event on TABLE livestreams TYPE record;
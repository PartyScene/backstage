DEFINE table users schemafull;
DEFINE FIELD first_name on table users type string;
DEFINE FIELD last_name on table users type string;
DEFINE FIELD email on table users type string;
DEFINE FIELD password on table users type string;

Define table events schemafull;
define field name on table events type string;
define field price on table events type decimal;
define field is_live on table events type option<bool> default false;
define field organizer on table events type record;
define field location on table events type geometry;

Rekate users->attends->events;
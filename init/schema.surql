DEFINE DATABASE OVERWRITE partyscene;
-- Define the main atomic table, the users table
DEFINE TABLE IF NOT EXISTS users schemafull;
DEFINE FIELD OVERWRITE first_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE bio ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE username ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE avatar ON TABLE users TYPE option<record<media>>;
DEFINE FIELD OVERWRITE sharedLoc ON TABLE users TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE hashed_password ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE hashed_email ON TABLE users TYPE string;

DEFINE EVENT OVERWRITE hash_pass ON TABLE users WHEN $event = "CREATE" THEN {UPDATE $after SET hashed_password = crypto::argon2::generate(hashed_password)};
DEFINE EVENT OVERWRITE hash_email ON TABLE users WHEN $event = "CREATE" THEN {UPDATE $after SET hashed_email = crypto::argon2::generate(hashed_email)};


DEFINE TABLE IF NOT EXISTS credentials SCHEMAFULL;
DEFINE FIELD OVERWRITE user ON TABLE credentials TYPE record<users>;
DEFINE FIELD OVERWRITE encrypted_data ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE data_initialization_vector ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE encrypted_decryption_key ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE decryption_key_initialization_vector ON TABLE credentials TYPE bytes;

DEFINE FIELD OVERWRITE created_at ON TABLE credentials TYPE datetime DEFAULT time::now();



DEFINE TABLE IF NOT EXISTS leads SCHEMAFULL;
DEFINE FIELD OVERWRITE usecase ON TABLE leads TYPE string;
DEFINE FIELD OVERWRITE encrypted_data ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE data_initialization_vector ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE encrypted_decryption_key ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE decryption_key_initialization_vector ON TABLE leads TYPE bytes;

DEFINE FIELD OVERWRITE created_at ON TABLE leads TYPE datetime DEFAULT time::now();




-- Let's define a relation table for users and events to record attendance
DEFINE TABLE IF NOT EXISTS attends TYPE RELATION IN users TO events;

-- Now let's define the events table
DEFINE TABLE OVERWRITE events SCHEMALESS;
DEFINE FIELD OVERWRITE title ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE description ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE price ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE status ON TABLE events TYPE string DEFAULT 'scheduled';
DEFINE FIELD OVERWRITE is_private ON TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE host ON TABLE events TYPE record<users>;
DEFINE FIELD OVERWRITE created_at ON TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE time ON TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE categories ON TABLE events TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE location ON TABLE events FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE location.address ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE location.coordinates ON TABLE events FLEXIBLE TYPE object;
DEFINE FIELD OVERWRITE metadata ON TABLE events FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE degree_of_freedom ON TABLE events TYPE int DEFAULT 1;
-- DEFINE FIELD OVERWRITE embeddings.text ON TABLE events TYPE array DEFAULT [];
DEFINE INDEX hnsw_event_text_embeddings ON TABLE events FIELDS embeddings.text HNSW DIMENSION 512 M 16 EFC 200;

-- Relate Events to Media
DEFINE TABLE OVERWRITE has_media TYPE RELATION IN events TO media;

-- Let's define a table for livestreams
DEFINE TABLE IF NOT EXISTS livestreams schemafull;
DEFINE FIELD OVERWRITE channel_name ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE input_name ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE ingest_url ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE playback_url ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE manifests ON TABLE livestreams TYPE array<string>;
DEFINE FIELD OVERWRITE event ON TABLE livestreams TYPE record<events>;

-- Let's define a table for scenes???
DEFINE TABLE IF NOT EXISTS scenes schemafull;
DEFINE FIELD OVERWRITE input_uid ON TABLE scenes TYPE STRING;
DEFINE FIELD OVERWRITE srt ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE event ON TABLE scenes TYPE record<events>;
DEFINE FIELD OVERWRITE srtPlayback ON TABLE scenes TYPE OBJECT;
DEFINE FIELD OVERWRITE created_at ON TABLE scenes TYPE datetime DEFAULT time::now();

-- A table for posts
DEFINE TABLE OVERWRITE posts SCHEMALESS TYPE RELATION IN users TO media;
DEFINE FIELD OVERWRITE out ON TABLE posts TYPE record<media>;
DEFINE FIELD OVERWRITE in ON TABLE posts TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE posts TYPE string;
DEFINE FIELD OVERWRITE created_at ON TABLE posts TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE metadata ON TABLE posts FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE event ON TABLE posts TYPE record<events>;
DEFINE INDEX hnsw_post_content_embeddings ON TABLE posts FIELDS embeddings.text HNSW DIMENSION 512 M 16 EFC 200;

DEFINE INDEX unique_posts ON TABLE posts COLUMNS in, out UNIQUE;
-- Define a vector index on the posts table for embedding field

-- A table for comments
DEFINE TABLE IF NOT EXISTS comments TYPE RELATION IN users TO posts;
DEFINE FIELD OVERWRITE out ON TABLE comments TYPE record<posts>;
DEFINE FIELD OVERWRITE in ON TABLE comments TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE comments TYPE string;
DEFINE FIELD OVERWRITE created_at ON TABLE comments TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_comments ON TABLE comments COLUMNS in, out UNIQUE;

-- A table for friends
DEFINE TABLE OVERWRITE friends TYPE RELATION IN users to users;
DEFINE FIELD OVERWRITE out ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE since ON TABLE friends TYPE datetime DEFAULT time::now();

DEFINE INDEX unique_friends ON TABLE friends COLUMNS in, out UNIQUE;

-- & Finally? A table for media
DEFINE TABLE OVERWRITE media SCHEMALESS;
-- Define fields with literal types
DEFINE FIELD OVERWRITE type ON media TYPE "image/jpeg" | "image/jpg" | "image/png" | "video/mp4" | "vod";
-- DEFINE FIELD OVERWRITE url ON media VALUE <future> {http::get(string::concat('http://34.144.227.188/media/sign?filename=', filename))} ASSERT string::len($value) > 0;

DEFINE FIELD OVERWRITE metadata ON media FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE filename ON media TYPE string DEFAULT "";

-- Metadata fields
DEFINE FIELD OVERWRITE uploaded_at ON media TYPE datetime DEFAULT time::now();

-- Relations
DEFINE FIELD OVERWRITE creator ON media TYPE record<users>;
DEFINE FIELD OVERWRITE event ON media TYPE option<record<events>>;

-- Define embedding fields for events
-- DEFINE FIELD OVERWRITE embeddings ON TABLE media FLEXIBLE TYPE object DEFAULT {};
-- DEFINE FIELD OVERWRITE embeddings.media ON TABLE media TYPE array DEFAULT array::range(1, 512);
DEFINE INDEX hnsw_media_embeddings ON TABLE media FIELDS embeddings HNSW DIMENSION 768 M 16 EFC 200;






DEFINE FUNCTION fn::fetch_events_by_location($coordinates: Point, $distance: number, $is_live: option<bool>, $page: option<number>, $limit: option<number>) {

    LET $page =
        IF (type::is::number($page)) THEN
            $page;
        ELSE
            1;
        END;
    
    LET $limit = 
        IF (type::is::number($limit)) THEN
            $limit;
        ELSE
            50;
        END;

    RETURN (

        SELECT *,
            (->has_media->media.{creator, metadata,  filename}) AS media,
            <-attends<-users AS attendees,
            array::len(<-attends<-users) as attendees_count,
            geo::distance(location.coordinates, $coordinates) as distance
        OMIT embeddings
        FROM events
        WHERE 
            is_live = $live 
            AND geo::distance(location.coordinates, $coordinates) <= $distance
        ORDER BY distance ASC
        LIMIT $limit START ($page - 1) * $limit
    )
    
};


DEFINE FUNCTION fn::fetch_all_events($page: number, $limit: number, $private: option<bool>) {


    LET $page =
        IF (type::is::number($page)) THEN
            $page;
        ELSE
            1;
        END;
    
    LET $limit = 
        IF (type::is::number($limit)) THEN
            $limit;
        ELSE
            50;
        END;


    RETURN (

        SELECT *,
        (->has_media->media.{creator, metadata,  filename}) AS media,
        <-attends<-users AS attendees,
        array::len(<-attends<-users) as attendees_count
    OMIT embeddings
    FROM events
    WHERE is_private = $private
    ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit
    )
    
};

DEFINE FUNCTION OVERWRITE fn::fetch_event($event_id: record) {
    RETURN (
        SELECT
        *,
        (->has_media->media.{creator, metadata,  filename}) AS media,
        <-attends<-users AS attendees,
        array::len(<-attends<-users) as attendees_count
    OMIT embeddings
    FROM ONLY $event_id
    )
};

DEFINE FUNCTION OVERWRITE fn::create_relationship($origin: record, $target: record, $status: string) {
    -- Check existing relationship
    LET $existing = (
        SELECT VALUE <->friends.* FROM $origin
        WHERE <->friends[WHERE out = $target OR in = $target]
    );
    
    -- Create new relationship if none exists
    LET $new = IF(array::len($existing) == 0) THEN (
        -- Create bidirectional relationship
        RELATE ONLY $origin -> friends -> $target SET
            status = $status,
            created_at = time::now()
    ) ELSE $existing
    END;
    
    RETURN {
        relationship: $new,
        is_new: array::len($existing) == 0
    }
};



DEFINE FUNCTION OVERWRITE fn::find_relationships($origin: record) {
    LET $result = SELECT
                            ->friends->users.* AS degree_1, 
                            ->friends->users->friends->users.* AS degree_2, 
                            ->friends->users->friends->users->friends->users.* AS degree_3,
                            ->friends->users->friends->users->friends->users->friends->users.* AS degree_4,
                            ->friends->users->friends->users->friends->users->friends->users->friends->users.* AS degree_5,
                            ->friends->users->friends->users->friends->users->friends->users->friends->users->friends->users.* AS degree_6
    
    FROM ONLY $origin;
    RETURN $result
};
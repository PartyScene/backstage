DEFINE DATABASE OVERWRITE partyscene;
-- Define the main atomic table, the users table
DEFINE TABLE OVERWRITE users SCHEMALESS;
DEFINE FIELD OVERWRITE first_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE bio ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE username ON TABLE users TYPE option<string> DEFAULT "";
DEFINE FIELD OVERWRITE avatar ON TABLE users TYPE string | record<media> DEFAULT "";
DEFINE FIELD OVERWRITE kyc_status ON TABLE users TYPE bool DEFAULT false;
DEFINE FIELD OVERWRITE kyc_payment_status ON TABLE users TYPE bool DEFAULT false;
DEFINE FIELD OVERWRITE sharedLoc ON TABLE users TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE hashed_password ON TABLE users TYPE option<string>;
DEFINE FIELD OVERWRITE hashed_email ON TABLE users TYPE option<string>;
DEFINE FIELD OVERWRITE auth_provider ON TABLE users TYPE string DEFAULT "password";
DEFINE FIELD OVERWRITE google_sub ON TABLE users TYPE option<string>;
DEFINE FIELD OVERWRITE stripe_account_id ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE stripe_account_kyc_status ON TABLE users TYPE bool DEFAULT false;
DEFINE FIELD OVERWRITE updated_at ON TABLE users TYPE datetime VALUE time::now();

DEFINE EVENT OVERWRITE hash_pass ON TABLE users WHEN $event = "CREATE" AND auth_provider = "password" THEN {UPDATE $after SET hashed_password = crypto::argon2::generate(hashed_password)};
DEFINE EVENT OVERWRITE hash_email ON TABLE users WHEN $event = "CREATE" THEN {UPDATE $after SET hashed_email = crypto::argon2::generate(hashed_email)};

DEFINE TABLE OVERWRITE credentials SCHEMAFULL;
DEFINE FIELD OVERWRITE user ON TABLE credentials TYPE record<users>;
DEFINE FIELD OVERWRITE encrypted_data ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE data_initialization_vector ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE encrypted_decryption_key ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE decryption_key_initialization_vector ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE updated_at ON TABLE credentials TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE credentials TYPE datetime DEFAULT time::now();



DEFINE TABLE OVERWRITE leads SCHEMAFULL;
DEFINE FIELD OVERWRITE usecase ON TABLE leads TYPE string;
DEFINE FIELD OVERWRITE encrypted_data ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE data_initialization_vector ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE encrypted_decryption_key ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE decryption_key_initialization_vector ON TABLE leads TYPE bytes;
DEFINE FIELD OVERWRITE updated_at ON TABLE leads TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE leads TYPE datetime DEFAULT time::now();


DEFINE TABLE OVERWRITE reports SCHEMALESS;
DEFINE FIELD OVERWRITE reporter ON TABLE reports TYPE record<users>;
DEFINE FIELD OVERWRITE reason ON TABLE reports TYPE string;
DEFINE FIELD OVERWRITE updated_at ON TABLE reports TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE reports TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE status ON TABLE reports TYPE string DEFAULT "pending";
DEFINE FIELD OVERWRITE metadata ON TABLE reports FLEXIBLE TYPE option<object> DEFAULT {};
DEFINE FIELD OVERWRITE resource ON TABLE reports TYPE option<record>;

-- Let's define a relation table for users and events to record attendance
DEFINE TABLE OVERWRITE attends TYPE RELATION IN users TO events;
DEFINE EVENT OVERWRITE update_attendee_count ON TABLE attends WHEN $event = "CREATE" THEN {UPDATE $after.out SET attendee_count = attendee_count + 1};
DEFINE INDEX unique_attendance ON TABLE attends COLUMNS in, out UNIQUE;

-- Now let's define the events table
DEFINE TABLE OVERWRITE events SCHEMALESS;
DEFINE FIELD OVERWRITE title ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE description ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE price ON TABLE events TYPE number;
DEFINE FIELD OVERWRITE status ON TABLE events TYPE string DEFAULT 'scheduled';
DEFINE FIELD OVERWRITE is_private ON TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE is_free ON TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE host ON TABLE events TYPE record<users>;
DEFINE FIELD OVERWRITE updated_at ON TABLE events TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE time ON TABLE events TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE categories ON TABLE events TYPE array<string> DEFAULT [];
DEFINE FIELD OVERWRITE location ON TABLE events FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE location.address ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE location.coordinates ON TABLE events FLEXIBLE TYPE point;
DEFINE FIELD OVERWRITE metadata ON TABLE events FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE degree_of_freedom ON TABLE events TYPE int DEFAULT 1;
DEFINE FIELD OVERWRITE attendee_count ON TABLE events TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE visible ON TABLE posts TYPE bool DEFAULT true;
-- DEFINE FIELD OVERWRITE embeddings.text ON TABLE events TYPE array DEFAULT [];
DEFINE INDEX hnsw_event_text_embeddings ON TABLE events FIELDS embeddings.text HNSW DIMENSION 512 M 16 EFC 200;


DEFINE TABLE OVERWRITE tickets SCHEMAFULL;
DEFINE FIELD OVERWRITE user ON TABLE tickets TYPE record<users>;
DEFINE FIELD OVERWRITE event ON TABLE tickets TYPE record<events>;
DEFINE FIELD OVERWRITE ticket_number ON TABLE tickets TYPE option<string>;
DEFINE FIELD OVERWRITE updated_at ON TABLE tickets TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE tickets TYPE datetime DEFAULT time::now();

DEFINE EVENT OVERWRITE update_ticket_number ON TABLE tickets WHEN $event = "CREATE" THEN {UPDATE $after SET ticket_number = 
    "TKT-" 
    + string::slice(<string>$after.event.id, 7, 4)
    + "-" 
    + rand::string(4)
    };



-- Relate Events to Media
DEFINE TABLE OVERWRITE has_media TYPE RELATION IN events TO media;

-- Let's define a table for livestreams
DEFINE TABLE OVERWRITE livestreams schemafull;
DEFINE FIELD OVERWRITE channel_name ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE input_name ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE ingest_url ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE playback_url ON TABLE livestreams type STRING;
DEFINE FIELD OVERWRITE manifests ON TABLE livestreams TYPE array<string>;
DEFINE FIELD OVERWRITE event ON TABLE livestreams TYPE record<events>;

-- Let's define a table for scenes???
DEFINE TABLE OVERWRITE scenes schemafull;
DEFINE FIELD OVERWRITE input_uid ON TABLE scenes TYPE STRING;
DEFINE FIELD OVERWRITE srt ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE event ON TABLE scenes TYPE record<events>;
DEFINE FIELD OVERWRITE srtPlayback ON TABLE scenes TYPE OBJECT;
DEFINE FIELD OVERWRITE updated_at ON TABLE scenes TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE scenes TYPE datetime DEFAULT time::now();

-- A table for posts
DEFINE TABLE OVERWRITE posts SCHEMALESS TYPE RELATION IN users TO media;
DEFINE FIELD OVERWRITE out ON TABLE posts TYPE record<media>;
DEFINE FIELD OVERWRITE in ON TABLE posts TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE posts TYPE string;
DEFINE FIELD OVERWRITE updated_at ON TABLE posts TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE posts TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE metadata ON TABLE posts FLEXIBLE TYPE object DEFAULT {};
DEFINE FIELD OVERWRITE event ON TABLE posts TYPE record<events>;
DEFINE FIELD OVERWRITE visible ON TABLE posts TYPE bool DEFAULT true;
DEFINE INDEX hnsw_post_content_embeddings ON TABLE posts FIELDS embeddings.text HNSW DIMENSION 512 M 16 EFC 200;

DEFINE INDEX unique_posts ON TABLE posts COLUMNS in, out UNIQUE;
-- Define a vector index on the posts table for embedding field

-- A table for comments
DEFINE TABLE OVERWRITE comments TYPE RELATION IN users TO posts;
DEFINE FIELD OVERWRITE out ON TABLE comments TYPE record<posts>;
DEFINE FIELD OVERWRITE in ON TABLE comments TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE comments TYPE string;
DEFINE FIELD OVERWRITE updated_at ON TABLE comments TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE comments TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_comments ON TABLE comments COLUMNS in, out UNIQUE;

-- A table for friends
DEFINE TABLE OVERWRITE friends TYPE RELATION IN users to users;
DEFINE FIELD OVERWRITE out ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE since ON TABLE friends TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON TABLE friends TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE friends TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_friends ON TABLE friends COLUMNS in, out UNIQUE;

-- & Finally? A table for media
DEFINE TABLE OVERWRITE media SCHEMALESS;
-- Define fields with literal types
DEFINE FIELD OVERWRITE type ON TABLE media TYPE "image/jpeg" | "image/jpg" | "image/png" | "video/mp4" | "video/quicktime" | "vod";
DEFINE FIELD OVERWRITE metadata ON media FLEXIBLE TYPE option<object> DEFAULT {};
DEFINE FIELD OVERWRITE filename ON media TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE status ON media TYPE string DEFAULT "pending";
DEFINE FIELD OVERWRITE updated_at ON media TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON media TYPE datetime DEFAULT time::now();

-- Metadata fields
DEFINE FIELD OVERWRITE uploaded_at ON media TYPE datetime DEFAULT time::now();

-- Relations
DEFINE FIELD OVERWRITE creator ON media TYPE record<users>;
DEFINE FIELD OVERWRITE event ON media TYPE option<record<events>>;

-- Define embedding fields for events
-- DEFINE FIELD OVERWRITE embeddings ON TABLE media FLEXIBLE TYPE object DEFAULT {};
-- DEFINE FIELD OVERWRITE embeddings.media ON TABLE media TYPE array DEFAULT array::range(1, 512);
DEFINE INDEX hnsw_media_embeddings ON TABLE media FIELDS embeddings HNSW DIMENSION 768 M 16 EFC 200;






DEFINE FUNCTION OVERWRITE fn::fetch_events_by_location($coordinates: Point, $distance: number, $is_live: option<bool>, $is_private: option<bool>, $user:option<record<users>>, $page: option<number>, $limit: option<number>) {

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

        SELECT fn::fetch_event(id) AS event, geo::distance(location.coordinates, $coordinates) as distance
        FROM events
        WHERE 
            is_live = $is_live 
            AND geo::distance(<Point>location.coordinates, $coordinates) <= $distance 
            AND (
                    IF $is_private { fn::exists_in_degree($user, host, 4) AND $is_private } 
                    ELSE {is_private = false}
                )
        ORDER BY distance ASC
        LIMIT $limit START ($page - 1) * $limit
    )
    
};


-- 
DEFINE FUNCTION OVERWRITE fn::fetch_public_events($page: number, $limit: number) {


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

        SELECT fn::fetch_event(id) AS event, created_at FROM events WHERE is_private = false AND time > time::now()
     ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_user_tickets($origin: record, $page: option<number>, $limit: option<number>) {

    LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    RETURN (
        SELECT id, out.* as event, (SELECT * FROM tickets WHERE user = $parent.in AND event = $parent.out) AS tickets
        FROM attends WHERE in = $origin
        LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_attended_events($origin: record, $page: option<number>, $limit: option<number>) {

    LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    RETURN (
        SELECT ->attends.{out.*, id} AS events_attended FROM ONLY $origin
        LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_created_events($origin: record, $page: option<number>, $limit: option<number>) {

    LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    RETURN (
        SELECT * FROM events WHERE creator = $origin
        LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_event($event_id: record) {
    RETURN (
        SELECT
        *,
        (->has_media->media.{creator, metadata,  filename, url}) AS media,
        <-attends<-users AS attendees,
        host.{id, first_name, last_name, avatar, filename}
    OMIT embeddings
    FROM ONLY $event_id
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_post($post_id: record) {
    RETURN (
        SELECT
        *,
        (out.{creator, filename}) AS media
    FROM ONLY $post_id
    )
};

DEFINE FUNCTION OVERWRITE fn::create_relationship($origin: record, $target: record, $status: string) {
    -- Check existing relationship
    LET $existing = (SELECT VALUE ->(friends WHERE out = $target OR in = $target).* FROM ONLY $origin);
    LET $new = IF !$existing THEN
        (RELATE ONLY $origin -> friends -> $target SET status = $status, created_at = time::now())
    ELSE
        $existing[0]
    END;
    RETURN {
        is_new: !$existing,
        relationship: $new
    }
};

DEFINE FUNCTION OVERWRITE fn::get_friends($origin: record) {
    RETURN (
        SELECT <->friends.{id, in, out, status} AS friends FROM $origin
    )
};

DEFINE FUNCTION OVERWRITE fn::find_relationships($origin: record) {
    LET $result = SELECT
                            @.{1}<->(friends WHERE status='accepted')<->users AS degree_1,
                            @.{2}<->(friends WHERE status='accepted')<->users AS degree_2,
                            @.{3}<->(friends WHERE status='accepted')<->users AS degree_3,
                            @.{4}<->(friends WHERE status='accepted')<->users AS degree_4,
                            @.{5}<->(friends WHERE status='accepted')<->users AS degree_5
    FROM ONLY $origin;
    RETURN $result
};

DEFINE FUNCTION OVERWRITE fn::exists_in_degree($origin: record, $target: record, $degree: number) {
    LET $tree = fn::find_relationships($origin);
    FOR $i IN 1..=$degree {
      LET $field = "degree_" + <string>$i;
        IF $target IN $tree[$field] OR $target IN $tree[$field]{
            RETURN true;
        }
    };
    RETURN false;
};
--
DEFINE FUNCTION OVERWRITE fn::fetch_private_events_for_user($user: record, $page: number, $limit: number) {


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
        SELECT fn::fetch_event(id) AS event, created_at FROM events
    WHERE is_private = true AND fn::exists_in_degree($user, host, degree_of_freedom) AND time > time::now()
    ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit
    )
};


DEFINE FUNCTION OVERWRITE fn::fetch_similar_events($event: record) {
    -- LET $media_embeddings = (SELECT VALUE embeddings from media WHERE event = $event);
    LET $media_embeddings = SELECT VALUE (->has_media->media.embeddings) FROM $event;
    
    LET $sum = $media_embeddings.reduce(
        |$a, $b| vector::add($a, $b)
        );
        
    LET $average_media_embeddings = vector::scale(
        $sum, <float> 1 / $media_embeddings.len() 
        );
    
    LET $text_emb = (SELECT VALUE embeddings.text FROM $event);
    
    RETURN (
        SELECT fn::fetch_event(event), vector::distance::knn() - vector::similarity::cosine(event.embeddings.text, $text_emb[0]) AS distance 
        FROM media WHERE embeddings <|20, 40|> $average_media_embeddings 
        ORDER BY distance
    )
};
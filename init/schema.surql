DEFINE DATABASE OVERWRITE partyscene;
-- Define the main atomic table, the users table
DEFINE TABLE OVERWRITE users SCHEMALESS;
DEFINE FIELD OVERWRITE first_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE last_name ON TABLE users TYPE string;
DEFINE FIELD OVERWRITE organization_name ON TABLE users TYPE option<string> DEFAULT "";
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
DEFINE FIELD OVERWRITE apple_sub ON TABLE users TYPE option<string>;
DEFINE FIELD OVERWRITE stripe_account_id ON TABLE users TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE stripe_account_kyc_status ON TABLE users TYPE bool DEFAULT false;
DEFINE FIELD OVERWRITE paystack_subaccount_id ON TABLE users TYPE string DEFAULT "";

-- Host profile fields. Stable host-facing data is explicit; only `socials`
-- is flexible because the platform list is expected to grow.
DEFINE FIELD OVERWRITE cover_image ON TABLE users TYPE option<string | record<media>> DEFAULT NONE;
DEFINE FIELD OVERWRITE profile_slug ON TABLE users TYPE option<string>;
DEFINE FIELD OVERWRITE is_verified_host ON TABLE users TYPE option<bool> DEFAULT NONE;
DEFINE FIELD OVERWRITE host_since ON TABLE users TYPE option<datetime>;
DEFINE FIELD OVERWRITE organization_type ON TABLE users TYPE option<string>;
DEFINE FIELD OVERWRITE socials ON TABLE users FLEXIBLE TYPE option<object> DEFAULT NONE;

DEFINE FIELD OVERWRITE scheduled_deletion_at ON TABLE users TYPE option<datetime>;
DEFINE FIELD OVERWRITE last_active ON TABLE users TYPE option<datetime>;
DEFINE FIELD OVERWRITE updated_at ON TABLE users TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE users TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE email ON TABLE users TYPE option<string>;

DEFINE EVENT OVERWRITE hash_pass ON TABLE users WHEN $event = "CREATE" AND auth_provider = "password" THEN {UPDATE $after SET hashed_password = crypto::argon2::generate(hashed_password)};
DEFINE EVENT OVERWRITE hash_email ON TABLE users WHEN $event = "CREATE" THEN {UPDATE $after SET hashed_email = crypto::argon2::generate(hashed_email)};
DEFINE EVENT OVERWRITE hash_pass_update ON TABLE users WHEN $event = "UPDATE" AND $before.hashed_password != $after.hashed_password AND $after.hashed_password != NONE AND string::starts_with($after.hashed_password, "$argon2") = false THEN {UPDATE $after SET hashed_password = crypto::argon2::generate(hashed_password)};

DEFINE INDEX OVERWRITE unique_email ON TABLE users COLUMNS email UNIQUE;
DEFINE INDEX OVERWRITE idx_google_sub ON TABLE users COLUMNS google_sub;
DEFINE INDEX OVERWRITE idx_apple_sub ON TABLE users COLUMNS apple_sub;
DEFINE INDEX OVERWRITE idx_username ON TABLE users COLUMNS username;
DEFINE INDEX OVERWRITE idx_stripe_account ON TABLE users COLUMNS stripe_account_id;
DEFINE INDEX OVERWRITE idx_last_active ON TABLE users COLUMNS last_active;
DEFINE INDEX OVERWRITE unique_profile_slug ON TABLE users COLUMNS profile_slug UNIQUE;

DEFINE TABLE OVERWRITE credentials SCHEMAFULL;
DEFINE FIELD OVERWRITE user ON TABLE credentials TYPE record<users>;
DEFINE FIELD OVERWRITE encrypted_data ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE data_initialization_vector ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE encrypted_decryption_key ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE decryption_key_initialization_vector ON TABLE credentials TYPE bytes;
DEFINE FIELD OVERWRITE updated_at ON TABLE credentials TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE credentials TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE idx_credentials_user ON TABLE credentials COLUMNS user;



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
DEFINE INDEX OVERWRITE idx_report_reporter ON TABLE reports COLUMNS reporter;
DEFINE INDEX OVERWRITE idx_report_status ON TABLE reports COLUMNS status;

-- Let's define a relation table for users and events to record attendance
DEFINE TABLE OVERWRITE attends TYPE RELATION IN users TO events;
DEFINE EVENT OVERWRITE update_attendee_count ON TABLE attends WHEN $event = "CREATE" THEN {UPDATE $after.out SET attendee_count = attendee_count + 1};
DEFINE INDEX unique_attendance ON TABLE attends COLUMNS in, out UNIQUE;

-- Define guestlist relation table for event invitations
DEFINE TABLE OVERWRITE guestlists TYPE RELATION IN users TO events;
DEFINE FIELD OVERWRITE invited_by ON TABLE guestlists TYPE record<users>;
DEFINE FIELD OVERWRITE invited_at ON TABLE guestlists TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE status ON TABLE guestlists TYPE string DEFAULT "invited";
DEFINE FIELD OVERWRITE updated_at ON TABLE guestlists TYPE datetime VALUE time::now();
DEFINE INDEX unique_guestlist ON TABLE guestlists COLUMNS in, out UNIQUE;

-- Now let's define the events table
DEFINE TABLE OVERWRITE events SCHEMALESS;
DEFINE FIELD OVERWRITE title ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE description ON TABLE events TYPE string;
DEFINE FIELD OVERWRITE price ON TABLE events TYPE number;
DEFINE FIELD OVERWRITE status ON TABLE events TYPE string DEFAULT 'scheduled';
DEFINE FIELD OVERWRITE is_private ON TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE is_free ON TABLE events TYPE option<bool> DEFAULT false;
DEFINE FIELD OVERWRITE host ON TABLE events TYPE record<users>;
DEFINE FIELD OVERWRITE reminder_sent ON TABLE events TYPE option<datetime> DEFAULT NONE;  -- set when 1-hour reminder has been dispatched
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
DEFINE FIELD OVERWRITE duration ON TABLE events TYPE int DEFAULT 60;

-- DEFINE FIELD OVERWRITE embeddings.text ON TABLE events TYPE array DEFAULT [];
DEFINE INDEX hnsw_event_text_embeddings ON TABLE events FIELDS embeddings.text HNSW DIMENSION 512 M 16 EFC 200;
DEFINE INDEX OVERWRITE idx_event_host ON TABLE events COLUMNS host;
DEFINE INDEX OVERWRITE idx_event_status ON TABLE events COLUMNS status;
DEFINE INDEX OVERWRITE idx_event_time ON TABLE events COLUMNS time;
DEFINE INDEX OVERWRITE idx_event_privacy ON TABLE events COLUMNS is_private;
DEFINE INDEX OVERWRITE idx_event_private_time ON TABLE events COLUMNS is_private, time;


-- Ticket tiers (max 3 per event)
DEFINE TABLE OVERWRITE ticket_tiers SCHEMAFULL;
DEFINE FIELD OVERWRITE event ON TABLE ticket_tiers TYPE record<events>;
DEFINE FIELD OVERWRITE name ON TABLE ticket_tiers TYPE string;
DEFINE FIELD OVERWRITE price ON TABLE ticket_tiers TYPE number;
DEFINE FIELD OVERWRITE capacity ON TABLE ticket_tiers TYPE option<int>;
DEFINE FIELD OVERWRITE description ON TABLE ticket_tiers TYPE string DEFAULT "";
DEFINE FIELD OVERWRITE sold_count ON TABLE ticket_tiers TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE updated_at ON TABLE ticket_tiers TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE ticket_tiers TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE idx_tier_event ON TABLE ticket_tiers COLUMNS event;
DEFINE INDEX OVERWRITE unique_tier_name_event ON TABLE ticket_tiers COLUMNS event, name UNIQUE;

DEFINE TABLE OVERWRITE tickets SCHEMAFULL;
DEFINE FIELD OVERWRITE user ON TABLE tickets TYPE option<record<users>>;
DEFINE FIELD OVERWRITE guest_email ON TABLE tickets TYPE option<string>;
DEFINE FIELD OVERWRITE guest_name ON TABLE tickets TYPE option<string>;
DEFINE FIELD OVERWRITE event ON TABLE tickets TYPE record<events>;
DEFINE FIELD OVERWRITE tier ON TABLE tickets TYPE option<record<ticket_tiers>>;
DEFINE FIELD OVERWRITE ticket_number ON TABLE tickets TYPE option<string>;
DEFINE FIELD OVERWRITE checked_in_at ON TABLE tickets TYPE option<datetime>;
DEFINE FIELD OVERWRITE updated_at ON TABLE tickets TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE tickets TYPE datetime DEFAULT time::now();

DEFINE EVENT OVERWRITE update_ticket_number ON TABLE tickets WHEN $event = "CREATE" THEN {UPDATE $after SET ticket_number = 
    "TKT-" 
    + string::slice(<string>$after.event.id, 7, 4)
    + "-" 
    + rand::string(4)
    };
DEFINE EVENT OVERWRITE increment_tier_sold ON TABLE tickets WHEN $event = "CREATE" AND $after.tier != NONE THEN {
    UPDATE $after.tier SET sold_count += 1
    };
DEFINE INDEX OVERWRITE idx_ticket_user ON TABLE tickets COLUMNS user;
DEFINE INDEX OVERWRITE idx_ticket_guest_email ON TABLE tickets COLUMNS guest_email;
DEFINE INDEX OVERWRITE idx_ticket_event ON TABLE tickets COLUMNS event;
DEFINE INDEX OVERWRITE idx_ticket_tier ON TABLE tickets COLUMNS tier;
DEFINE INDEX OVERWRITE idx_ticket_number ON TABLE tickets COLUMNS ticket_number UNIQUE;
DEFINE INDEX OVERWRITE idx_ticket_user_event ON TABLE tickets COLUMNS user, event;



-- Relate Events to Media
DEFINE TABLE OVERWRITE has_media TYPE RELATION IN events TO media;

-- Let's define a table for scenes (Cloudflare Live)
DEFINE TABLE OVERWRITE scenes schemafull;
DEFINE FIELD OVERWRITE input_uid ON TABLE scenes TYPE STRING;
DEFINE FIELD OVERWRITE srt ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE srtPlayback ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE rtmps ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE rtmpsPlayback ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE webRTC ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE webRTCPlayback ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE playback ON TABLE scenes FLEXIBLE TYPE OBJECT;
DEFINE FIELD OVERWRITE metadata ON TABLE scenes FLEXIBLE TYPE OBJECT DEFAULT {};
DEFINE FIELD OVERWRITE event ON TABLE scenes TYPE record<events>;
DEFINE FIELD OVERWRITE user ON TABLE scenes TYPE record<users>;
DEFINE FIELD OVERWRITE live_started_at ON TABLE scenes TYPE option<datetime> DEFAULT NONE;
DEFINE FIELD OVERWRITE updated_at ON TABLE scenes TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE scenes TYPE datetime DEFAULT time::now();
DEFINE INDEX OVERWRITE idx_scene_event ON TABLE scenes COLUMNS event;
DEFINE INDEX OVERWRITE idx_scene_user ON TABLE scenes COLUMNS user;
DEFINE INDEX OVERWRITE unique_scene_event_user ON TABLE scenes COLUMNS event, user UNIQUE;

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
DEFINE INDEX OVERWRITE idx_post_event ON TABLE posts COLUMNS event;
DEFINE INDEX OVERWRITE idx_post_visible ON TABLE posts COLUMNS visible;
-- Define a vector index on the posts table for embedding field

-- A table for comments
DEFINE TABLE OVERWRITE comments TYPE RELATION IN users TO posts;
DEFINE FIELD OVERWRITE out ON TABLE comments TYPE record<posts>;
DEFINE FIELD OVERWRITE in ON TABLE comments TYPE record<users>;
DEFINE FIELD OVERWRITE content ON TABLE comments TYPE string;
DEFINE FIELD OVERWRITE updated_at ON TABLE comments TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE comments TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_comments ON TABLE comments COLUMNS in, out UNIQUE;

-- Collectors: users designated by a host to collect tap-to-pay
-- payments on their behalf for a specific event. Scoped per-event,
-- expires naturally when the event ends. Host must own the event.
DEFINE TABLE OVERWRITE event_collectors TYPE RELATION IN events TO users;
DEFINE FIELD OVERWRITE in ON TABLE event_collectors TYPE record<events>;
DEFINE FIELD OVERWRITE out ON TABLE event_collectors TYPE record<users>;
DEFINE FIELD OVERWRITE assigned_by ON TABLE event_collectors TYPE record<users>;
DEFINE FIELD OVERWRITE created_at ON TABLE event_collectors TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_event_collector ON TABLE event_collectors COLUMNS in, out UNIQUE;
DEFINE INDEX OVERWRITE idx_collector_event ON TABLE event_collectors COLUMNS in;
DEFINE INDEX OVERWRITE idx_collector_user ON TABLE event_collectors COLUMNS out;

-- A table for friends
DEFINE TABLE OVERWRITE friends TYPE RELATION IN users to users;
DEFINE FIELD OVERWRITE out ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE friends TYPE record<users>;
DEFINE FIELD OVERWRITE since ON TABLE friends TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON TABLE friends TYPE datetime VALUE time::now();
DEFINE FIELD OVERWRITE created_at ON TABLE friends TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE status ON TABLE friends TYPE "pending" | "accepted" | "blocked" | "removed" | "rejected" DEFAULT "pending";
DEFINE INDEX unique_friends ON TABLE friends COLUMNS in, out UNIQUE;

-- A table for blocks (user blocking functionality)
DEFINE TABLE OVERWRITE blocks TYPE RELATION IN users to users;
DEFINE FIELD OVERWRITE out ON TABLE blocks TYPE record<users>;
DEFINE FIELD OVERWRITE in ON TABLE blocks TYPE record<users>;
DEFINE FIELD OVERWRITE created_at ON TABLE blocks TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_blocks ON TABLE blocks COLUMNS in, out UNIQUE;

-- Host follower relation: follower (in) -> host (out). Counts and
-- "is_following" are computed at query time over the indexed edges.
DEFINE TABLE OVERWRITE host_followers TYPE RELATION IN users TO users;
DEFINE FIELD OVERWRITE in ON TABLE host_followers TYPE record<users>;
DEFINE FIELD OVERWRITE out ON TABLE host_followers TYPE record<users>;
DEFINE FIELD OVERWRITE created_at ON TABLE host_followers TYPE datetime DEFAULT time::now();
DEFINE INDEX unique_host_followers ON TABLE host_followers COLUMNS in, out UNIQUE;
DEFINE INDEX OVERWRITE idx_host_followers_host ON TABLE host_followers COLUMNS out;
DEFINE INDEX OVERWRITE idx_host_followers_follower ON TABLE host_followers COLUMNS in;

-- Host gallery relation: host (in) -> media (out). Reuses the existing
-- media table so the RMQ pipeline, metadata, blurhash, and signed URL
-- handling all keep working without a parallel storage path.
DEFINE TABLE OVERWRITE host_media TYPE RELATION IN users TO media;
DEFINE FIELD OVERWRITE in ON TABLE host_media TYPE record<users>;
DEFINE FIELD OVERWRITE out ON TABLE host_media TYPE record<media>;
DEFINE FIELD OVERWRITE caption ON TABLE host_media TYPE option<string>;
DEFINE FIELD OVERWRITE sort_order ON TABLE host_media TYPE int DEFAULT 0;
DEFINE FIELD OVERWRITE event ON TABLE host_media TYPE option<record<events>>;
DEFINE FIELD OVERWRITE created_at ON TABLE host_media TYPE datetime DEFAULT time::now();
DEFINE FIELD OVERWRITE updated_at ON TABLE host_media TYPE datetime VALUE time::now();
DEFINE INDEX unique_host_media ON TABLE host_media COLUMNS in, out UNIQUE;
DEFINE INDEX OVERWRITE idx_host_media_host ON TABLE host_media COLUMNS in;
DEFINE INDEX OVERWRITE idx_host_media_sort ON TABLE host_media COLUMNS in, sort_order;

-- & Finally? A table for media
DEFINE TABLE OVERWRITE media SCHEMALESS;
-- Define fields with literal types
DEFINE FIELD OVERWRITE type ON TABLE media TYPE "image/jpeg" | "image/jpg" | "image/png" | "image/heic" | "image/heif" | "image/webp" | "video/mp4" | "video/quicktime" | "vod";
DEFINE FIELD OVERWRITE metadata   ON media FLEXIBLE TYPE option<object> DEFAULT {};
DEFINE FIELD OVERWRITE claimed_at  ON media TYPE option<datetime>;  -- set when r18e claims a record to prevent double-processing
DEFINE FIELD OVERWRITE thumbnail ON media TYPE option<string>;  -- GCS path of video preview frame (.webp), set by RMQ pipeline
DEFINE FIELD OVERWRITE blurhash  ON media TYPE option<string>;  -- ~30-char BlurHash string for instant placeholder rendering
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
DEFINE INDEX OVERWRITE idx_media_creator ON TABLE media COLUMNS creator;
DEFINE INDEX OVERWRITE idx_media_event ON TABLE media COLUMNS event;
DEFINE INDEX OVERWRITE idx_media_status ON TABLE media COLUMNS status;
DEFINE INDEX OVERWRITE idx_media_type ON TABLE media COLUMNS type;






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


DEFINE FUNCTION OVERWRITE fn::fetch_all_events($page: number, $limit: number) {

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
        ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit
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

        SELECT fn::fetch_event(id) AS event, created_at FROM events WHERE is_private = false AND time + duration::from::mins(duration) > time::now()
     ORDER BY created_at ASC LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_trending_events($page: number, $limit: number) {
    -- Trending score per event:
    --   attendee_count * 3  — social proof (heaviest signal)
    --   post_count * 2      — activity / content signal (people are posting = event is live)
    -- Tiebreaker: soonest events first.
    -- Only surfaces future public events that haven't ended yet.

    LET $page  = IF (type::is::number($page))  THEN $page  ELSE 1  END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    RETURN (
        SELECT
            fn::fetch_event(id) AS event,
            time AS event_time, created_at,
            (
                (attendee_count * 3) +
                (count(SELECT id FROM posts WHERE event = $parent.id) * 2)
            ) AS score
        FROM events
        WHERE is_private = false
          AND time + duration::from::mins(duration) > time::now()
        ORDER BY score DESC, event_time ASC
        LIMIT $limit START ($page - 1) * $limit
    );
};

DEFINE FUNCTION OVERWRITE fn::fetch_user_tickets($origin: record, $page: option<number>, $limit: option<number>) {

    LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    RETURN (
        SELECT id, out.* AS event, (SELECT *, tier.{id, name, price, description} AS tier_info FROM tickets WHERE user = $parent.in AND event = $parent.out) AS tickets
        FROM attends WHERE in = $origin
        LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_attended_events($origin: record, $page: option<number>, $limit: option<number>) {

    LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    LET $event_ids = (SELECT VALUE ->attends.out.id FROM ONLY $origin LIMIT $limit START ($page - 1) * $limit);

    RETURN array::map($event_ids, |$id| { fn::fetch_event($id) });
};

DEFINE FUNCTION OVERWRITE fn::fetch_created_events($origin: record, $page: option<number>, $limit: option<number>) {

    LET $page = IF (type::is::number($page)) THEN $page ELSE 1 END;
    LET $limit = IF (type::is::number($limit)) THEN $limit ELSE 50 END;

    RETURN (
        SELECT *, (time + duration::from::mins(duration)) AS end_time FROM events WHERE creator = $origin
        LIMIT $limit START ($page - 1) * $limit
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_event($event_id: record) {
    RETURN (
        SELECT
        *,
        (time + duration::from::mins(duration)) AS end_time,
        (->has_media->media[WHERE event = $parent.id].{creator, metadata, filename, thumbnail, blurhash, url}) AS media,
        array::concat(<-attends<-users, (SELECT * FROM tickets WHERE event = $parent.id AND guest_email)) AS attendees,
        (SELECT * FROM tickets WHERE event = $parent.id AND checked_in_at != NONE) AS scanned_tickets,
        (SELECT * FROM tickets WHERE event = $parent.id AND checked_in_at = NONE) AS unscanned_tickets,
        host.{id, organization_name, first_name, last_name, avatar, filename, stripe_account_id},
        (SELECT id, name, price, capacity, description, sold_count FROM ticket_tiers WHERE event = $parent.id ORDER BY price ASC) AS tiers,
        (SELECT VALUE out.id FROM event_collectors WHERE in = $parent.id) AS collectors
    OMIT embeddings
    FROM ONLY $event_id
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_post($post_id: record) {
    RETURN (
        SELECT
        *,
        (out.{creator, metadata, filename}) AS media
    FROM ONLY $post_id
    )
};

DEFINE FUNCTION OVERWRITE fn::fetch_event_guestlist($event_id: record) {
    RETURN (
        SELECT 
            in.{id, organization_name, first_name, last_name, avatar, username} AS user,
            invited_by.{id, organization_name,first_name, last_name} AS invited_by,
            invited_at,
            status,
            updated_at
        FROM guestlists 
        WHERE out = $event_id
        ORDER BY invited_at DESC
    )
};

DEFINE FUNCTION OVERWRITE fn::create_relationship($origin: record, $target: record, $status: string) {
    -- Check existing relationship
    LET $existing = (SELECT VALUE <->(friends WHERE out = $target OR in = $target).* FROM ONLY $origin);
    LET $new = IF !$existing {
        (RELATE ONLY $origin -> friends -> $target SET status = $status, created_at = time::now())
    } ELSE IF $existing[0].status == 'removed' {
        UPDATE $existing[0] SET status = 'pending' RETURN AFTER
    } ELSE {
        $existing[0]
    };
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
    WHERE is_private = true AND fn::exists_in_degree($user, host, degree_of_freedom) AND time + duration::from::mins(duration) > time::now()
    ORDER BY created_at DESC LIMIT $limit START ($page - 1) * $limit
    )
};


-- ─────────────────────────────────────────────────────────────────────────────
-- fn::fetch_event_preview
-- Lightweight event card for recommendation/discovery surfaces.
-- Omits tickets, guestlists, and scanned/unscanned ticket lists.
-- Use fn::fetch_event for the full detail view.
-- ─────────────────────────────────────────────────────────────────────────────
DEFINE FUNCTION OVERWRITE fn::fetch_event_preview($event_id: record) {
    RETURN (
        SELECT
            id,
            title,
            description,
            time,
            (time + duration::from::mins(duration)) AS end_time,
            duration,
            location,
            price,
            is_free,
            is_private,
            status,
            categories,
            created_at,
            (->has_media->media[WHERE event = $parent.id].{creator, metadata, filename, thumbnail, blurhash, url}) AS media,
            host.{id, organization_name, first_name, last_name, avatar, filename},
            count(<-attends<-users) AS attendee_count
        OMIT embeddings
        FROM ONLY $event_id
    )
};

-- ─────────────────────────────────────────────────────────────────────────────
-- fn::fetch_similar_events
-- Finds up to $limit events visually similar to $event using HNSW KNN on
-- ViT-768 media embeddings. Returns lightweight preview cards.
--
-- Algorithm:
--   1. Collect media IDs via graph traversal, then SELECT embeddings in a
--      separate query. Direct dot-field access on traversal results auto-flattens
--      array fields in SurrealDB, collapsing [[vec1],[vec2]] to raw floats.
--      The separate SELECT returns one 768-dim array per row, which is what
--      vector::add requires.
--   2. Average them into one representative vector.
--   3. Run HNSW KNN search across all media records to find visually close
--      images, excluding media belonging to the source event itself.
--   4. Traverse each result back to its event (media.event field).
--   5. Deduplicate — multiple media hits from the same event collapse to one.
--   6. Filter to future events only, then return preview cards ordered by
--      best visual distance ascending (most similar first).
-- ─────────────────────────────────────────────────────────────────────────────
DEFINE FUNCTION OVERWRITE fn::fetch_similar_events($event: record, $limit: option<int>) {
    LET $k = IF type::is::int($limit) THEN $limit ELSE 10 END;

    -- Collect embeddings for this event's media.
    --
    -- IMPORTANT: do NOT use ->has_media->media.embeddings via graph traversal.
    -- In SurrealDB, dot-field access on a traversal result auto-flattens array
    -- fields, turning [[f1..f768],[f1..f768]] into [f1,f2,...] — raw floats
    -- that break vector::add. Instead: traverse for IDs, then SELECT separately
    -- so each row contributes one 768-dim array entry.
    LET $media_ids = (SELECT VALUE ->has_media->media FROM ONLY $event) OR [];
    LET $raw_vecs  = SELECT VALUE embeddings FROM media
                     WHERE id IN $media_ids AND embeddings != NONE;

    IF array::len($raw_vecs) = 0 { RETURN [] };

    -- Element-wise sum across all 768-dim vectors, then scale by 1/n.
    LET $avg_vec = vector::scale(
        $raw_vecs.reduce(|$a, $b| vector::add($a, $b)),
        <float>1 / array::len($raw_vecs)
    );

    -- HNSW ANN: fetch top-100 candidates by embedding similarity only.
    -- IMPORTANT: do NOT add AND predicates (event != $event, status = ...) inside
    -- the <|K,EF|> clause. SurrealDB evaluates extra predicates as pre-filters on
    -- the index traversal phase; if they can't be resolved there the whole query
    -- returns []. All filtering is done as explicit post-steps below.
    LET $knn_raw = SELECT
            id       AS media_id,
            event    AS event_id,
            status,
            vector::distance::knn() AS dist
        FROM media
        WHERE embeddings <|100, 40|> $avg_vec;

    -- Post-filter 1: drop media with no event, wrong status, or from source event.
    LET $candidates = $knn_raw.filter(|$r|
        $r.event_id != NONE
        AND $r.event_id != $event
        AND $r.status  = 'completed'
    );

    IF array::len($candidates) = 0 { RETURN [] };

    -- Deduplicate: one row per event, keeping the closest media hit.
    LET $deduped = SELECT event_id, math::min(dist) AS best_dist
        FROM $candidates
        GROUP BY event_id;

    -- Post-filter 2: future events only (not yet ended).
    LET $scored = $deduped.filter(|$r| {
        LET $info = (SELECT time, duration FROM ONLY $r.event_id);
        $info != NONE
            AND $info.time + duration::from::mins($info.duration) > time::now()
    });

    RETURN (
        SELECT
            fn::fetch_event_preview(event_id) AS event,
            best_dist AS visual_distance
        FROM $scored
        ORDER BY best_dist ASC
        LIMIT $k
    )
};
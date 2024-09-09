
# PartyScene Backend

Okay so a briefing of what this is, we will be creating a  dynamic social media and gathering platform built on a microservices architecture. This design ensures scalability, maintainability, and flexibility. The app leverages Quart for backend development and SurrealDB for a flexible, scalable database.

## Each API will be it's own micro-service.

We're gonna start out with each API being it's own microservice, I really wouldn't do this but all the AI suggested it.

#### API REFERENCE (Lets start with users).
### USERS MICROSERVICE

#### Fetch a user profile
```http
  GET /users/:id/
```

| Parameter | Type     | Description                |
| :-------- | :------- | :------------------------- |
| `id` | `string` | **Required**. User ID |

#### Fetches a user's friends.

```http
  GET /users/:id/friends
```

| Parameter | Type     | Description                       |
| :-------- | :------- | :-------------------------------- |
| `id`      | `string` | **Required**. ID of user to fetch |

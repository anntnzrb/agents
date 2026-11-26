# Hono Backend Stack Reference (2026)



## Section index


# 1. Create project
mkdir my-api && cd my-api
bun init -y

# 2. Install dependencies
bun add hono hono-openapi @scalar/hono-api-reference @hono/swagger-ui zod

# 3. Add TypeScript
bun add -d typescript @types/bun

# 4. Write app.ts (copy from section 2 above)
# 5. Run
bun run --hot app.ts
```

Endpoints after startup:
- `GET /health`: health check
- `GET /hello?name=world`: documented route
- `POST /users`: validated JSON body route
- `GET /openapi.json`: raw OpenAPI 3.1.0 spec
- `GET /scalar`: Scalar API Reference UI
- `GET /swagger`: Swagger UI

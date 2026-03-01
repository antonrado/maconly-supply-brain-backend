# WB API Capabilities Map and Token Setup

## 1) Sources

- WB API root: https://dev.wildberries.ru/
- General API rules: https://dev.wildberries.ru/en/openapi/api-information
- Product management (Content + Prices/Discounts): https://dev.wildberries.ru/en/docs/openapi/work-with-products
- Marketplace orders and logistics:
  - FBS: https://dev.wildberries.ru/en/docs/openapi/orders-fbs
  - DBW: https://dev.wildberries.ru/en/docs/openapi/orders-dbw
  - DBS: https://dev.wildberries.ru/en/docs/openapi/orders-dbs
  - In-Store Pickup: https://dev.wildberries.ru/en/docs/openapi/in-store-pickup
  - FBW Supplies: https://dev.wildberries.ru/en/docs/openapi/orders-fbw
- Reports (Statistics): https://dev.wildberries.ru/en/docs/openapi/reports
- Finance and Documents: https://dev.wildberries.ru/en/docs/openapi/financial-reports-and-accounting
- Analytics and Data: https://dev.wildberries.ru/en/docs/openapi/analytics
- Marketing and Promotion: https://dev.wildberries.ru/en/docs/openapi/promotion
- Questions, feedback, chat, buyer returns: https://dev.wildberries.ru/en/docs/openapi/user-communication
- Tariffs (commission, box/pallet, return tariffs): https://dev.wildberries.ru/en/docs/openapi/wb-tariffs

## 2) Global WB API Rules (important for integration)

- Authorization uses `Authorization` header with API token.
- Token validity is 180 days from creation.
- WB API uses rate limits with token-bucket behavior.
- Relevant rate-limit headers:
  - `X-Ratelimit-Remaining`
  - `X-Ratelimit-Retry`
  - `X-Ratelimit-Limit`
  - `X-Ratelimit-Reset`
- When throttled, API returns `429 Too Many Requests`.
- Some categories have special accounting (for example certain `409` responses may count as multiple requests).

## 3) Token Types (WB side)

- Personal access token: intended for your own software/infrastructure; highest trust and sensitivity.
- Service token: for a specific cloud service from WB business solutions catalog.
- Base token: limited access for general use cases.
- Test token: sandbox-only test data.

This project should use your personal access token in read-only mode.

## 4) Capability Coverage by Enabled Sections

The provided token was created with read-only access for all selected sections.

### 4.1 Content

Primary docs: `work-with-products`

Main capabilities:
- categories/subjects/characteristics lookup
- product card lists and metadata
- media and tags operations
- seller warehouses and inventory operations
- prices and discount data/operations

Example endpoints:
- `/content/v2/object/parent/all`
- `/content/v2/object/all`
- `/content/v2/get/cards/list`
- `/api/v3/warehouses`
- `/api/v3/stocks/{warehouseId}`

Primary host: `content-api.wildberries.ru`

### 4.2 Marketplace

Primary docs: `orders-fbs`, `orders-dbw`, `orders-dbs`, `in-store-pickup`

Main capabilities:
- get new/completed orders
- statuses and status transitions
- labels/stickers
- order metadata
- supplies/passes flows (for FBS)

Example endpoints:
- `/api/v3/orders/new` (FBS)
- `/api/v3/dbw/orders/new` (DBW)
- `/api/v3/dbs/orders/new` (DBS)
- `/api/v3/click-collect/orders/new` (In-Store pickup)

Primary host: `marketplace-api.wildberries.ru`

### 4.3 Statistics

Primary docs: `reports`

Main capabilities:
- sales feed
- orders feed
- stock feed
- warehouse remains and other report tasks

Example endpoints:
- `/api/v1/supplier/sales`
- `/api/v1/supplier/orders`
- `/api/v1/supplier/stocks`

Primary host: `statistics-api.wildberries.ru`

### 4.4 Finance

Primary docs: `financial-reports-and-accounting`

Main capabilities:
- account balance
- realization report details

Example endpoints:
- `/api/v1/account/balance`
- `/api/v5/supplier/reportDetailByPeriod`

Primary host: `finance-api.wildberries.ru` (balance), plus `statistics-api.wildberries.ru` (realization report endpoint path in docs)

### 4.5 Analytics

Primary docs: `analytics`

Main capabilities:
- sales funnel reports
- search query analytics
- stock reports (group/product/size/warehouse)
- downloadable analytics reports

Example endpoints:
- `/api/analytics/v3/sales-funnel/products`
- `/api/v2/stocks-report/products/groups`
- `/api/v2/stocks-report/offices`

Primary host: `seller-analytics-api.wildberries.ru`

### 4.6 Promotion

Primary docs: `promotion`

Main capabilities:
- campaign lists/details
- campaign management and bids
- promotion calendar
- ad finance and statistics

Example endpoints:
- `/adv/v1/promotion/count`
- `/api/advert/v2/adverts`
- `/adv/v3/fullstats`
- `/api/v1/calendar/promotions`

Primary host: `advert-api.wildberries.ru`

### 4.7 Questions and Reviews

Primary docs: `user-communication`

Main capabilities:
- unseen/unanswered counters
- list questions and feedbacks
- reply/edit replies
- archive and pin management

Example endpoints:
- `/api/v1/new-feedbacks-questions`
- `/api/v1/questions`
- `/api/v1/feedbacks`
- `/api/feedbacks/v1/pins`

Primary host: `feedbacks-api.wildberries.ru`

### 4.8 Prices and Discounts

Primary docs: `work-with-products` (Prices and Discounts section)

Main capabilities:
- upload price/discount tasks
- check processing status
- list goods with prices
- size prices and club discounts

Example endpoints:
- `/api/v2/upload/task`
- `/api/v2/history/tasks`
- `/api/v2/list/goods/filter`

Primary host: `discounts-prices-api.wildberries.ru`

### 4.9 Chat with Buyer

Primary docs: `user-communication` (Buyers Chat section)

Main capabilities:
- chat list
- chat events
- send messages
- file download

Example endpoints:
- `/api/v1/seller/chats`
- `/api/v1/seller/events`
- `/api/v1/seller/message`

Primary host: `buyer-chat-api.wildberries.ru`

### 4.10 Deliveries (Supplies)

Primary docs: `orders-fbw` (+ FBS supplies inside `orders-fbs`)

Main capabilities:
- acceptance options
- warehouse and transit direction data
- supply list/details/goods/package

Example endpoints:
- `/api/v1/supplies`
- `/api/v1/supplies/{ID}`
- `/api/v1/supplies/{ID}/goods`

Primary host: `supplies-api.wildberries.ru`

### 4.11 Returns

Primary docs:
- buyer returns: `user-communication` (Buyers Returns)
- return tariffs: `wb-tariffs`

Main capabilities:
- buyer return claims and responses
- return tariff visibility

Example endpoints:
- `/api/v1/claims`
- `/api/v1/claim`
- `/api/v1/tariffs/return`

Primary hosts: `returns-api.wildberries.ru` and tariff host from `wb-tariffs`

### 4.12 Documents

Primary docs: `financial-reports-and-accounting` (Documents section)

Main capabilities:
- document categories
- document list
- document download (single and bulk)

Example endpoints:
- `/api/v1/documents/categories`
- `/api/v1/documents/list`
- `/api/v1/documents/download`
- `/api/v1/documents/download/all`

Primary host: `documents-api.wildberries.ru`

## 5) Current Backend State (maconly-supply-brain-backend)

Current implementation stores WB token in DB table `wb_integration_accounts.api_token`.

Important current constraints:
- There is no dedicated API endpoint to create/update WB integration accounts yet.
- Existing `GET /api/v1/planning/integrations/config-snapshot` intentionally hides all tokens.

So token insertion currently must be done at DB level.

## 6) Step-by-Step: Where to Put the Token Right Now

### Step 1. Keep token out of git/history as much as possible

In PowerShell, set temporary session variable:

```powershell
$env:WB_API_TOKEN = "<PASTE_YOUR_PERSONAL_READONLY_TOKEN>"
```

### Step 2. Ensure DB is up and migrations are applied

```powershell
.\scripts\dev.ps1 up
```

### Step 3. Check current WB integration rows

```powershell
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -c "SELECT id, name, supplier_id, is_active, created_at, updated_at FROM wb_integration_accounts ORDER BY id;"
```

### Step 4A. Insert a new WB account row (if none exists)

```powershell
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -v wb_token="$env:WB_API_TOKEN" -c "INSERT INTO wb_integration_accounts (name, supplier_id, api_token, is_active) VALUES ('WB Personal RO', NULL, :'wb_token', true);"
```

### Step 4B. Or update an existing row (recommended when rotating token)

```powershell
docker compose -f .\docker-compose.yml exec -T db psql -U maconly -d maconly_db -v wb_token="$env:WB_API_TOKEN" -c "UPDATE wb_integration_accounts SET api_token = :'wb_token', is_active = true, updated_at = now() WHERE id = <EXISTING_ID>;"
```

### Step 5. Verify that API does not expose secrets

```powershell
curl.exe -s http://localhost:8000/api/v1/planning/integrations/config-snapshot
```

Expected: account metadata is visible, but no `api_token` field/value is returned.

### Step 6. Optional check in monitoring summary

```powershell
curl.exe -s http://localhost:8000/api/v1/planning/monitoring/snapshot
```

`integrations.wb_accounts_total` and `integrations.wb_accounts_active` should reflect the inserted/updated account.

## 7) Security Notes

- Never hardcode token in repository files.
- `.env*` files are ignored by `.gitignore`, but this project currently reads only `DATABASE_URL` from env by default.
- Keep token read-only unless write access is truly required.
- Rotate token before 180-day expiration.
- If token is exposed, revoke and recreate immediately in WB seller portal.

## 8) Recommended Next Engineering Step

Add a dedicated secured backend contract for integration accounts:
- `POST/PATCH /api/v1/planning/integrations/wb-accounts`
- encrypted storage strategy for `api_token`
- masked token preview only (last N chars)
- explicit token rotation flow

Then build the first outbound WB API client calls for Economic Alpha inputs:
- commission (`/api/v1/tariffs/commission`)
- operational sales (`/api/v1/supplier/sales`)
- realization detail (`/api/v5/supplier/reportDetailByPeriod`)
- stock analytics (`/api/v2/stocks-report/products/groups`)
- supply statuses (`/api/v1/supplies`)

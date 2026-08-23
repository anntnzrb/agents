# Trust & Deal Scoring Engine Reference

Specification and mathematical formulations for evaluating digital subscriptions, accounts, and licenses across secondary digital marketplaces.

## Composite Scoring Formula

The Trust and Deal Score ($S \in [0, 100]$) evaluates an offer across four weighted pillars:

$$S = \text{clamp}\left(0, 100, 0.30 \cdot S_{\text{price}} + 0.30 \cdot S_{\text{seller}} + 0.25 \cdot S_{\text{format}} + 0.15 \cdot S_{\text{warranty}} - \sum P_{\text{redflags}}\right)$$

## 1. Price Sanity Score ($S_{\text{price}}$)

Evaluates the ratio $R = \text{Price} / \text{MSRP}$ against estimated standard retail pricing:

- $R < 0.05$ (Extreme micro-price): Score = $20$. Flagged as high-risk micro-dump (high fraud or stolen token likelihood).
- $0.05 \le R < 0.10$: Score = $50$.
- $0.10 \le R \le 0.50$: Score = $100$. Peak sweet spot for regional arbitrage and promotional links.
- $0.50 < R \le 0.75$: Score = $80$. Fair discount.
- $0.75 < R \le 1.00$: Score = $50$. Low discount margin.
- $R > 1.00$: Score = $30$. Overpriced relative to retail.

## 2. Seller Reliability Score ($S_{\text{seller}}$)

Combines Bayesian smoothed positive feedback with log-scaled verified sales volume:

$$S_{\text{seller}} = 0.60 \cdot \left(\frac{\text{Pos} \cdot N + 95 \cdot 50}{N + 50}\right) + 0.40 \cdot \min\left(100, 20 \cdot \log_{10}(\max(1, N))\right)$$

Where:
- $\text{Pos}$: Positive review percentage ($0 - 100$).
- $N$: Total verified sales or review count.

## 3. Delivery Format Classification ($S_{\text{format}}$)

- `DEDICATED_ACCOUNT`: Base Score = $95$. Full private credentials (`login:password:recovery_email`).
- `BUYER_EMAIL_UPGRADE`: Base Score = $90$. Upgrade or family invite applied directly to buyer's personal email.
- `PROMO_LINK_OR_CODE`: Base Score = $85$. Single-use partner voucher or activation URL.
- `STUDENT_PACK`: Base Score = $65$. Pre-activated educational pack credentials.
- `SHARED_POOL`: Base Score = $30$. Shared account across multiple simultaneous users.
- `SESSION_COOKIE`: Base Score = $0$. Raw session token or cookie injection.

## 4. Warranty & Guarantee Score ($S_{\text{warranty}}$)

- $\ge 30\text{ days}$: Score = $100$.
- $14 - 29\text{ days}$: Score = $85$.
- $7 - 13\text{ days}$: Score = $70$.
- $1 - 6\text{ days}$: Score = $50$.
- $0\text{ days / None}$: Score = $30$.

## 5. Red-Flag Penalties & Circuit Breakers

### Red-Flag Penalty Dictionary
- Session cookie / token injection: $-100\text{ pts}$ (Fatal).
- Carded / cracked / stolen origin: $-100\text{ pts}$ (Fatal).
- Shared multi-user pool / multi-device: $-40\text{ pts}$.
- Short lifetime / change password in 1 hour: $-35\text{ pts}$.
- No replacement warranty: $-30\text{ pts}$.
- Reported ban risk: $-25\text{ pts}$.

### Hard Circuit Breakers
Any of the following immediately sets $S = 5$ and tier to `CONFIRMED_SCAM`:
1. Format is `SESSION_COOKIE` or description contains cookie injection methods.
2. Seller positive feedback is below $75\%$.
3. Price ratio is extremely low on a dedicated account for a premium service.

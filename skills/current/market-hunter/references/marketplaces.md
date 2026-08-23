# Marketplace Profiles, Catalog Breakdown & Priority Routing

Comprehensive reference on supported marketplace adapters, catalog specialties, buyer protections, and optimal search priority routing.

## Marketplace Catalog Specialties & Strengths

### 1. G2A (`g2a`)
- **Primary Catalog Strengths**:
  - Brand promotional trial and activation links (e.g. Google AI Gemini Pro multi-month activation links).
  - Software license keys and global retail software.
  - Gaming gift cards and prepaid subscription cards.
- **Why It Is Good**:
  - High inventory of legitimate brand partnership promo codes.
  - Native PayPal and Apple Pay integration with instant automated key delivery.
  - Strong buyer protection and dispute resolution.
- **Top Product Sweet Spots**:
  - Google Gemini Pro multi-month global activation links.
  - Windows Pro and Office retail license keys.
- **When to Prioritize G2A**: Prioritize when searching for Google AI / Gemini Advanced activation links or when PayPal payment protection is required.

---

### 2. Plati.Market (`plati`)
- **Primary Catalog Strengths**:
  - Direct wholesale pre-activated AI accounts (`login:password` format).
  - GitHub Copilot annual student and open-source developer packs.
  - Windows, Office, and Microsoft OEM lifetime keys.
  - Adobe Creative Cloud enterprise and student team seats.
  - Canva Pro lifetime team invites.
- **Why It Is Good**:
  - The direct wholesale bazaar where resellers from other platforms source inventory.
  - Lowest base prices on the web with minimal reseller markup.
  - Automated instant text delivery (credentials displayed on screen seconds after payment).
  - High-volume sellers with tens of thousands of verified positive sales.
- **Top Product Sweet Spots**:
  - ChatGPT Plus dedicated personal accounts with email access.
  - GitHub Copilot 1-year developer accounts.
  - Windows Pro lifetime retail keys.
  - Canva Pro lifetime team access.
- **When to Prioritize Plati**: Prioritize when looking for dedicated ChatGPT Plus accounts, GitHub Copilot annual licenses, or permanent software OEM keys.

---

### 3. Kinguin (`kinguin`)
- **Primary Catalog Strengths**:
  - Perplexity Pro annual promotional keys (telecom and device partner codes).
  - Gemini Advanced subscriptions.
  - VPN subscriptions (NordVPN, Surfshark, ExpressVPN multi-year keys).
  - Security, antivirus, and utility software licenses.
- **Why It Is Good**:
  - Clean payment checkout with low processing fees.
  - Fast automated digital dispatch.
  - High availability of annual promotional campaign codes.
- **Top Product Sweet Spots**:
  - Perplexity Pro 1-year promo redemption keys.
  - Multi-year VPN accounts and security suites.
- **When to Prioritize Kinguin**: Prioritize when looking for Perplexity Pro annual codes, VPN subscriptions, or clean payment checkouts.

---

### 4. Z2U (`z2u`)
- **Primary Catalog Strengths**:
  - Cursor Pro pre-activated accounts and team seats.
  - Claude Pro dedicated accounts and team workspace seats.
  - Raw pre-created Google and Gmail accounts (PVA, aged profiles, bulk packs).
  - Multi-account developer packs for automated scraping and agent load-balancing.
- **Why It Is Good**:
  - Built specifically for digital account transfers, PVA emails, and developer multi-accounts.
  - Direct P2P seller live chat before and after purchase.
  - Large inventory of aged, high-trust email accounts.
- **Top Product Sweet Spots**:
  - Cursor Pro monthly accounts.
  - Claude Pro accounts.
  - Bulk Gmail PVA accounts and aged Google accounts.
- **When to Prioritize Z2U**: Prioritize when looking for Cursor Pro IDE accounts, Claude Pro access, or bulk Google/Gmail infrastructure.

---

### 5. FunPay (`funpay`)
- **Primary Catalog Strengths**:
  - Discord Nitro annual gifts with server boosts.
  - Telegram Premium annual subscriptions (via TON blockchain and regional gifts).
  - Streaming family slot upgrades (Spotify Premium, YouTube Premium, Apple Music).
  - Custom balance top-ups (Zhipu BigModel, DeepSeek prepaid credits).
- **Why It Is Good**:
  - Strict buyer-first escrow protection: the seller receives zero funds until the buyer tests the account and confirms the order.
  - Direct peer-to-peer pricing with zero reseller markups.
  - Seller online status indicators and live messaging.
- **Top Product Sweet Spots**:
  - Discord Nitro annual gifts.
  - Telegram Premium annual subscriptions.
  - YouTube Premium and Spotify Premium personal email family upgrades.
- **When to Prioritize FunPay**: Prioritize for Discord Nitro, Telegram Premium, personal email streaming upgrades, or when strict escrow verification is required.

---

## Optimal Product-to-Marketplace Priority Routing

When searching for specific services, query the highest-priority marketplaces first:

| Target Category / Service | Primary Marketplace | Secondary Marketplace | Typical Savings vs Retail |
| :--- | :--- | :--- | :---: |
| **Google Gemini Advanced 2TB (3M/6M)** | **G2A** | **Kinguin** | Heavy Discount |
| **ChatGPT Plus (Dedicated Account)** | **Plati.Market** | **FunPay** | Wholesale Level |
| **GitHub Copilot (1 Year)** | **Plati.Market** | **Z2U** | Heavy Discount |
| **Claude Pro (Dedicated / Team)** | **Z2U** | **FunPay** | Significant Savings |
| **Perplexity Pro (1 Year Code)** | **Kinguin** | **Eneba** | Heavy Discount |
| **Cursor Pro (Monthly)** | **Z2U** | **FunPay** | Significant Savings |
| **Bulk Google / Gmail Accounts (PVA/Aged)** | **Z2U** | **Plati.Market** | Wholesale Rates |
| **Discord Nitro & Telegram Premium** | **FunPay** | **Plati.Market** | Heavy Discount |
| **Spotify & YouTube Premium (Family Upgrade)** | **FunPay** | **Plati.Market** | Heavy Discount |
| **Windows 11 & Office 2024 (Retail/OEM)** | **Plati.Market** | **Kinguin** | Heavy Discount |

---

## How to Add a New Marketplace Adapter

To add a new marketplace (for example, `eneba` or `gamivo`):

1. Create `lib/adapters/<name>.ts` implementing the `MarketplaceAdapter` interface.
2. Register the adapter in `lib/adapters/index.ts` using `registerAdapter(new NewAdapter())`.
3. The core engine will automatically include the new marketplace in multi-market scans without requiring any changes to CLI or scoring logic.

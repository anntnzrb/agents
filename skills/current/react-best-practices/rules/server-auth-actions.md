---
title: Authenticate and Authorize Server Actions
impact: HIGH
impactDescription: prevents unauthorized mutations
tags: server, security, server-actions, authentication, authorization
---

## Authenticate and Authorize Server Actions

Treat each Server Action reachable from the client as a public mutation entrypoint: its UI may be hidden, but a caller can invoke it with a direct POST request. Validate every argument and perform authentication and authorization inside every reachable mutation (or a server-only DAL it calls); a page-level check does not protect the action.

**Incorrect (page guard does not protect the action):**

```tsx
export default async function AdminPage() {
  const session = await auth()
  if (!session?.user?.isAdmin) redirect('/login')
  return <form action={deleteAllUsers}>Delete</form>
}

export async function deleteAllUsers() {
  'use server'
  await db.user.deleteMany()
}
```

The page guard controls rendered UI only; a direct caller can invoke the exported action.

**Correct (checks the mutation boundary):**

```tsx
import { z } from 'zod'
import { auth } from '@/lib/auth'
import { db } from '@/lib/db'

export async function deleteUser(id: unknown) {
  'use server'
  const userId = z.string().uuid().parse(id)
  const session = await auth()
  if (!session?.user) throw new Error('Unauthorized')
  const resource = await db.user.findUnique({ where: { id: userId } })
  if (!resource || !canDeleteUser(session.user, resource)) {
    throw new Error('Forbidden')
  }
  await db.user.delete({ where: { id: userId } })
}
```

`canDeleteUser` must enforce the applicable resource- or tenant-level authorization, not only authentication.


**Source:** [Next.js: How to think about data security](https://nextjs.org/docs/app/guides/data-security#authentication-and-authorization)

**Provenance:** Clean-room rule derived from the current official Next.js documentation (accessed 2026-07-16); no plugin prose copied.

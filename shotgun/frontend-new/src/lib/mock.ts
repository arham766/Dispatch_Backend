import { Incident } from "./types";

export const MOCK_DIFF = `diff --git a/services/checkout/src/handlers/place-order.ts b/services/checkout/src/handlers/place-order.ts
index 2a1f7c4..b3d92e1 100644
--- a/services/checkout/src/handlers/place-order.ts
+++ b/services/checkout/src/handlers/place-order.ts
@@ -12,12 +12,18 @@ export async function placeOrder(req: Request, res: Response) {
   const { userId, cartId, paymentMethodId } = req.body;

-  const cart = await cartRepo.findById(cartId);
-  if (cart.userId !== userId) {
-    return res.status(403).json({ error: "forbidden" });
+  const cart = await cartRepo.findById(cartId);
+  if (!cart) {
+    return res.status(404).json({ error: "cart_not_found" });
+  }
+  if (cart.userId !== userId) {
+    return res.status(403).json({ error: "forbidden" });
   }

-  const total = cart.items.reduce((sum, item) => sum + item.price * item.qty, 0);
+  const total = cart.items.reduce(
+    (sum, item) => sum + Math.round(item.price * 100) * item.qty,
+    0,
+  ) / 100;

   const order = await orderRepo.create({
     userId,
diff --git a/services/checkout/test/place-order.test.ts b/services/checkout/test/place-order.test.ts
index 8c7e1a9..f4b2c83 100644
--- a/services/checkout/test/place-order.test.ts
+++ b/services/checkout/test/place-order.test.ts
@@ -45,6 +45,16 @@ describe("placeOrder", () => {
     expect(res.status).toHaveBeenCalledWith(403);
   });

+  it("returns 404 when cart is missing", async () => {
+    cartRepo.findById.mockResolvedValueOnce(null);
+    await placeOrder(reqWith({ cartId: "missing" }), res);
+    expect(res.status).toHaveBeenCalledWith(404);
+  });
+
+  it("computes totals without float drift", async () => {
+    cartRepo.findById.mockResolvedValueOnce(cartWithPennyItems());
+    await placeOrder(reqWith({ cartId: "c1" }), res);
+    expect(orderRepo.create).toHaveBeenCalledWith(
+      expect.objectContaining({ total: 19.99 }),
+    );
+  });
 });
`;

export interface SupportingMaterial {
  id: string;
  label: string;
  caption?: string;
  thumbnail: string;
  src: string;
  kind: "screenshot" | "log" | "trace";
  accent?: string;
}

export const MOCK_MATERIALS: SupportingMaterial[] = [
  { id: "m1", label: "Sentry trace", caption: "503 · checkout-api", thumbnail: "", src: "#", kind: "trace", accent: "#e85d1a" },
  { id: "m2", label: "Stack trace", caption: "place-order.ts:18", thumbnail: "", src: "#", kind: "log", accent: "#ffe4a8" },
  { id: "m3", label: "Datadog log", caption: "p99 → 4.2s", thumbnail: "", src: "#", kind: "log", accent: "#4ade80" },
  { id: "m4", label: "Cart payload", caption: "items: 3 · null", thumbnail: "", src: "#", kind: "screenshot", accent: "#9c9c9c" },
];

export const MOCK_INCIDENT: Incident = {
  id: "inc_01HX",
  service: "checkout-api",
  symptom: "POST /orders returns 500 when cart is missing",
  status: "RESOLVED",
  diagnosis:
    "placeOrder dereferences cart without a null check when cartRepo.findById returns null. " +
    "A floating-point reduction on item prices also drifts on long carts, returning totals that " +
    "fail downstream validation. Fix adds the null guard and switches the reduce to integer cents.",
  before: {
    screenshot: "",
    replay_url: "https://kaneai.lambdatest.com/replays/before-1",
    caption: "500 on POST /orders",
    accent: "#f87171",
  },
  after: {
    screenshot: "",
    replay_url: "https://kaneai.lambdatest.com/replays/after-1",
    caption: "200 OK — order placed",
    accent: "#4ade80",
  },
  diff_url: "/api/incidents/inc_01HX/diff",
  pr_url: "https://github.com/dispatch-demo/checkout-api/pull/482",
  updated_at: "2026-05-30T10:24:00Z",
};

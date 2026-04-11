/**
 * Tina4 Store — tina4-js PWA Frontend
 *
 * Demonstrates: signals, computed, web components, PWA registration,
 * WebSocket order tracking, SSE sales feed, API client.
 */
const { signal, computed, html, Tina4Element, api, ws, sse, pwa } = Tina4;

// ── PWA Registration ──────────────────────────────────────────
pwa.register({
    name: "Tina4 Store",
    shortName: "T4Store",
    themeColor: "#2d6a4f",
    backgroundColor: "#fefae0",
    display: "standalone",
    cacheStrategy: "network-first",
    precache: ["/", "/products", "/css/tina4.min.css", "/css/store.css"],
    offlineRoute: "/offline"
});

// ── Reactive Cart State ───────────────────────────────────────
const cartCount = signal(0);

// Fetch initial count from session
api.get("/api/cart/count").then(r => {
    if (r.body && typeof r.body.count === "number") {
        cartCount.value = r.body.count;
    }
});

// Cart badge web component — updates reactively when cartCount changes
class CartBadge extends Tina4Element {
    render() {
        const count = cartCount.value;
        if (count === 0) return html``;
        return html`<span class="badge-cart">${count}</span>`;
    }
}
customElements.define("cart-badge", CartBadge);

// ── Add to Cart (AJAX) ───────────────────────────────────────
document.querySelectorAll("[data-add-to-cart]").forEach(btn => {
    btn.addEventListener("click", async (e) => {
        e.preventDefault();
        const productId = btn.dataset.addToCart;
        const qty = parseInt(btn.dataset.qty || "1", 10);
        const result = await api.post("/api/cart", {
            product_id: parseInt(productId, 10),
            quantity: qty
        });
        if (result.http_code === 200) {
            cartCount.value += qty;
            // Brief visual feedback
            btn.textContent = "Added!";
            btn.disabled = true;
            setTimeout(() => {
                btn.textContent = btn.dataset.label || "Add to Cart";
                btn.disabled = false;
            }, 1000);
        }
    });
});

// ── WebSocket Order Tracking ──────────────────────────────────
const orderStatus = signal("pending");
const orderMessages = signal([]);

function trackOrder(orderId) {
    const socket = frond.ws(`ws://${location.hostname}:7146/ws/orders`, {
        reconnect: true,
        reconnectDelay: 3000,
        onOpen: function() {
            socket.send({ action: "track", order_id: orderId });
        }
    });

    socket.on("message", function(data) {
        if (data.event === "status_changed") {
            orderStatus.value = data.status;
        }
        orderMessages.value = [...orderMessages.value, data];
    });
}

// Order tracker web component
class OrderTracker extends Tina4Element {
    connectedCallback() {
        super.connectedCallback();
        const orderId = this.getAttribute("order-id");
        const initialStatus = this.getAttribute("status") || "pending";
        orderStatus.value = initialStatus;
        if (orderId) {
            trackOrder(parseInt(orderId, 10));
        }
    }

    render() {
        const statuses = ["pending", "processing", "shipped", "delivered"];
        const current = statuses.indexOf(orderStatus.value);
        return html`
            <div class="order-tracker">
                ${statuses.map((s, i) => html`
                    <div class="step ${i <= current ? 'active' : ''}">
                        <div class="dot"></div>
                        <span>${s}</span>
                    </div>
                `)}
            </div>
        `;
    }
}
customElements.define("order-tracker", OrderTracker);

// ── SSE Admin Sales Feed ──────────────────────────────────────
// SSE is handled by the inline script in dashboard.twig (toast + ticker)
// to avoid duplicate EventSource connections.

// ── GraphQL Product Search ────────────────────────────────────
(function() {
    var searchInput = document.getElementById("product-search");
    var searchResults = document.getElementById("search-results");
    if (!searchInput || !searchResults) return;

    var debounceTimer = null;

    searchInput.addEventListener("input", function() {
        clearTimeout(debounceTimer);
        var term = searchInput.value.trim();

        if (term.length < 2) {
            searchResults.classList.remove("open");
            searchResults.innerHTML = "";
            return;
        }

        debounceTimer = setTimeout(function() {
            frond.graphql("/api/graphql",
                '{ search_products(term: "' + term.replace(/"/g, '\\"') + '", limit: 8) { id name slug price image_url } }',
                {},
                function(data, errors) {
                    if (errors || !data || !data.search_products) {
                        searchResults.classList.remove("open");
                        return;
                    }

                    var products = data.search_products;
                    if (products.length === 0) {
                        searchResults.innerHTML = '<div class="search-empty">No products found</div>';
                        searchResults.classList.add("open");
                        return;
                    }

                    var items = "";
                    for (var i = 0; i < products.length; i++) {
                        var p = products[i];
                        items += '<a href="/products/' + p.slug + '" class="search-item">'
                            + '<img src="' + (p.image_url || '/img/placeholder.png') + '" alt="">'
                            + '<div class="search-item-info">'
                            + '<div class="search-item-name">' + p.name + '</div>'
                            + '<div class="search-item-price">$' + Number(p.price).toFixed(2) + '</div>'
                            + '</div></a>';
                    }
                    searchResults.innerHTML = items;
                    searchResults.classList.add("open");
                }
            );
        }, 300);
    });

    // Close dropdown when clicking outside
    document.addEventListener("click", function(e) {
        if (!searchInput.contains(e.target) && !searchResults.contains(e.target)) {
            searchResults.classList.remove("open");
        }
    });

    // Close on Escape
    searchInput.addEventListener("keydown", function(e) {
        if (e.key === "Escape") {
            searchResults.classList.remove("open");
            searchInput.blur();
        }
    });
})();

// ── Language Switcher ─────────────────────────────────────────
document.querySelectorAll("[data-lang]").forEach(btn => {
    btn.addEventListener("click", async () => {
        await api.get(`/api/locale/${btn.dataset.lang}`);
        location.reload();
    });
});

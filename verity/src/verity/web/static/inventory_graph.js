// ──────────────────────────────────────────────────────────────
// MODEL INVENTORY — PRODUCTION GRAPH
//
// Renders a three-lane network diagram of champion executables
// (agents + tasks) with their wired-up prompts, configs, tools,
// and inter-agent delegations.
//
// Data: fetched once from /admin/model-inventory/graph-data.
// Filters and visibility toggles are pure DOM ops on the loaded
// graph — no round-trips while exploring.
//
// URL state: filter selection is mirrored to the query string so
// a shared link reproduces the same view.
// ──────────────────────────────────────────────────────────────

(function () {
    'use strict';

    // ── CONSTANTS ────────────────────────────────────────────

    const GRAPH_DATA_URL = '/admin/model-inventory/graph-data';

    // Lane x-positions in Cytoscape model coordinates. The
    // values are picked so that the three lanes fit inside the
    // canvas at typical zoom (1.0) without horizontal scroll on
    // a ~1600 px viewport. Cytoscape pans / zooms freely so
    // exact pixel sizing isn't load-bearing.
    const LANE_X = {
        executable: 220,
        prompts_configs: 720,
        tools: 1180,
    };

    // Vertical spacing between stacked nodes within a lane.
    // 110px gives the 200×60 node rectangles enough breathing
    // room that long labels don't collide with neighbours.
    const ROW_HEIGHT = 110;
    const LANE_TOP   = 60;

    // Type → colour. Used for both the node border on the
    // Cytoscape canvas AND the icon-strip on the HTML label.
    // Values are kept in lockstep with inventory_graph.css —
    // change a colour here, change it there.
    const TYPE_COLOR = {
        agent:  '#2f855a', // green-700
        task:   '#2b6cb0', // blue-700
        prompt: '#6b46c1', // purple-700
        config: '#b7791f', // amber-700
        tool:   '#c53030', // red-700
    };

    // Icon glyphs — exactly the characters used in the
    // /admin sidebar nav (see base.html .verity-nav-icon).
    // Keeping them in lockstep with the sidebar means an
    // operator's eye links a node in the graph to its parent
    // section in the nav without having to learn a new code.
    //
    //   ⬡  Agents     (white hexagon)
    //   ☐  Tasks      (ballot box)
    //   ¶  Prompts    (pilcrow)
    //   ⚙  Configs    (gear)
    //   ⚒  Tools      (hammer & pick)
    //
    // CSS sizes the glyph with .ig-node-icon — change one,
    // change both.
    const ICONS = {
        agent:  '⬡',
        task:   '☐',
        prompt: '¶',
        config: '⚙',
        tool:   '⚒',
    };

    // Node-type human label for the tooltip and any controls
    // that need to render the type as text.
    const TYPE_LABEL = {
        agent:  'Agent',
        task:   'Task',
        prompt: 'Prompt',
        config: 'Config',
        tool:   'Tool',
    };

    // ── MODULE STATE ─────────────────────────────────────────

    let cy = null;            // Cytoscape instance
    let allApplications = []; // {id, name, label}
    let selectedNodeId = null;

    // ── INIT ────────────────────────────────────────────────

    async function init() {
        const container = document.getElementById('inventory-graph');
        if (!container) return;

        let payload;
        try {
            const resp = await fetch(GRAPH_DATA_URL);
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            payload = await resp.json();
        } catch (e) {
            container.innerHTML =
                '<div class="inventory-graph-error">' +
                'Failed to load graph data: ' + escapeHtml(String(e)) +
                '</div>';
            return;
        }

        allApplications = payload.applications || [];
        populateAppFilter(allApplications);

        // Lay out nodes in lanes BEFORE handing them to Cytoscape;
        // the 'preset' layout reads x/y off the data and trusts us.
        const laidOut = assignLanes(payload.nodes || []);

        cy = cytoscape({
            container: container,
            elements: {
                nodes: laidOut,
                edges: payload.edges || [],
            },
            layout: { name: 'preset' },
            style: cyStyle(),
            wheelSensitivity: 0.2,
            minZoom: 0.3,
            maxZoom: 2.0,
        });

        // Bolt on HTML node labels via the plugin loaded in the
        // template. The selector '*' applies to every node; per-
        // node markup is built in nodeHtmlLabel() below using
        // the data fields we set on each node.
        if (typeof cy.nodeHtmlLabel === 'function') {
            cy.nodeHtmlLabel([{
                // Explicit 'node' selector so the plugin only
                // matches nodes — defensive against any version
                // that interprets '*' to include other elements.
                query: 'node',
                valign: 'center',
                halign: 'center',
                valignBox: 'center',
                halignBox: 'center',
                tpl: nodeHtmlLabel,
            }]);
        }

        renderLegend();    // Renders the Show / Legend rows.
        wireGraphInteractions();
        wireControlBar();
        applyUrlState();   // Restore filters from query string.
        applyFilters();    // Initial render with restored / default filters.
        cy.fit(undefined, 60);
    }

    // ── LANE LAYOUT ──────────────────────────────────────────

    function assignLanes(nodes) {
        // Group nodes by which lane they belong to, then stack
        // each group vertically with a fixed row height. Within
        // a lane, sub-grouping keeps related node types together:
        //   Lane 1: agents above tasks.
        //   Lane 2: prompts above configs.
        //   Lane 3: tools.
        const lanes = {
            agent:  [], task: [],
            prompt: [], config: [],
            tool:   [],
        };
        for (const n of nodes) {
            if (n && n.data && lanes[n.data.node_type]) {
                lanes[n.data.node_type].push(n);
            }
        }

        // Sort each bucket by display label for a stable order
        // — flipping a filter shouldn't reshuffle the whole graph.
        for (const k of Object.keys(lanes)) {
            lanes[k].sort((a, b) =>
                (a.data.label || '').localeCompare(b.data.label || ''));
        }

        const stacked = [];
        const stackLane = (laneX, buckets) => {
            let y = LANE_TOP;
            for (const bucket of buckets) {
                for (const n of bucket) {
                    stacked.push({
                        ...n,
                        position: { x: laneX, y: y },
                    });
                    y += ROW_HEIGHT;
                }
                // Small gap between sub-groups (e.g. agents → tasks).
                if (bucket.length) y += 30;
            }
        };

        stackLane(LANE_X.executable,      [lanes.agent, lanes.task]);
        stackLane(LANE_X.prompts_configs, [lanes.prompt, lanes.config]);
        stackLane(LANE_X.tools,           [lanes.tool]);

        return stacked;
    }

    // ── CYTOSCAPE STYLE ─────────────────────────────────────

    function cyStyle() {
        // Most of the visual content lives in the HTML labels
        // we render via the plugin. Cytoscape itself draws the
        // node bounding box (a coloured rounded rectangle) and
        // the edges. We hide the native text label since the
        // HTML overlay shows the same info more flexibly.
        return [
            {
                selector: 'node',
                style: {
                    // round-rectangle + small corner-radius
                    // matches the 8px CSS border-radius on the
                    // HTML overlay (.ig-node), so pan / zoom
                    // doesn't reveal a square corner under the
                    // overlay.
                    'shape': 'round-rectangle',
                    'corner-radius': 8,
                    'width': 220,
                    'height': 64,
                    'background-color': '#ffffff',
                    'border-width': 2,
                    'border-color':
                        'data(borderColor)',
                    'label': '',  // HTML label overlay handles text.
                    'text-opacity': 0,
                },
            },
            {
                selector: 'node.faded',
                style: {
                    'opacity': 0.18,
                },
            },
            {
                selector: 'node.highlighted',
                style: {
                    'border-width': 3,
                    'background-color': '#fef9c3', // pale yellow wash
                },
            },
            {
                selector: 'node.hidden',
                style: { 'display': 'none' },
            },
            {
                selector: 'edge',
                style: {
                    'curve-style': 'bezier',
                    'width': 1.5,
                    'line-color': '#94a3b8',
                    'target-arrow-shape': 'triangle',
                    'target-arrow-color': '#94a3b8',
                    'arrow-scale': 0.9,
                    'opacity': 0.7,
                },
            },
            // Edge type variants — colour each relationship type
            // so the network reads at a glance.
            {
                selector: 'edge[edge_type = "prompt"]',
                style: { 'line-color': '#a78bfa', 'target-arrow-color': '#a78bfa' },
            },
            {
                selector: 'edge[edge_type = "config"]',
                style: { 'line-color': '#fbbf24', 'target-arrow-color': '#fbbf24' },
            },
            {
                selector: 'edge[edge_type = "tool"]',
                style: { 'line-color': '#fca5a5', 'target-arrow-color': '#fca5a5' },
            },
            {
                selector: 'edge[edge_type = "delegation"]',
                style: {
                    'line-color': '#1f2937',
                    'target-arrow-color': '#1f2937',
                    'line-style': 'dashed',
                    'curve-style': 'bezier',
                    'control-point-step-size': 80,
                    'width': 2,
                },
            },
            {
                selector: 'edge.highlighted',
                style: {
                    'opacity': 1,
                    'width': 3,
                },
            },
            {
                selector: 'edge.faded',
                style: { 'opacity': 0.08 },
            },
            {
                selector: 'edge.hidden',
                style: { 'display': 'none' },
            },
        ];
    }

    // Cytoscape's render pipeline calls cyStyle() once but it
    // reads back the data attributes lazily. That means we need
    // the colour as a data attribute on each node. We add it
    // when assembling laid-out nodes — done here as a post-step
    // so the SQL/JSON layer doesn't need to know about colours.
    // (Implemented inside cyStyle by reading data(borderColor);
    // assignLanes spreads existing data unchanged, so we set
    // borderColor in nodeHtmlLabel-time? No — set it on init.)
    //
    // Doing it here on the laid-out nodes:
    function annotateBorderColors(nodes) {
        for (const n of nodes) {
            n.data.borderColor = TYPE_COLOR[n.data.node_type] || '#475569';
        }
        return nodes;
    }

    // ── HTML NODE LABEL TEMPLATE ─────────────────────────────

    function nodeHtmlLabel(data) {
        // The cytoscape-node-html-label plugin re-renders this
        // template whenever a node's data changes. We exploit
        // that to hide the visible card by returning an empty
        // (display:none) div when applyFilters() has flagged
        // the node as filtered-out via data.hidden. Cytoscape's
        // own display-none style hides the underlying node and
        // edges, but the plugin's HTML overlay sits in a sibling
        // DOM tree and doesn't track display-none — so we have
        // to drive the overlay's visibility through data.
        if (data.hidden) {
            return '<div style="display:none"></div>';
        }
        const type = data.node_type;
        const color = TYPE_COLOR[type] || '#475569';
        const icon = ICONS[type] || '';

        // Subtitle differs per node type so each card communicates
        // the most useful one-liner without hover.
        let subtitle = '';
        if (type === 'agent' || type === 'task') {
            const bits = [];
            if (data.version) bits.push('v' + data.version);
            if (data.materiality) bits.push(data.materiality);
            subtitle = bits.join(' · ');
        } else if (type === 'prompt') {
            const bits = [];
            if (data.version) bits.push('v' + data.version);
            if (data.governance_tier) bits.push(data.governance_tier);
            subtitle = bits.join(' · ');
        } else if (type === 'config') {
            subtitle = data.model || '';
        } else if (type === 'tool') {
            subtitle = data.transport === 'python_inprocess'
                ? 'local'
                : (data.mcp_server_name
                    ? 'mcp · ' + data.mcp_server_name
                    : data.transport || '');
        }

        // Decision-count bubble — only on executables. Empty
        // string for everything else means no element renders.
        let bubble = '';
        if ((type === 'agent' || type === 'task')
                && typeof data.decision_count_30d === 'number') {
            bubble =
                '<div class="ig-node-bubble"' +
                ' style="background:' + color + ';"' +
                ' title="' + data.decision_count_30d +
                ' decisions in last 30 days">' +
                shortNumber(data.decision_count_30d) +
                '</div>';
        }

        return (
            '<div class="ig-node ig-node-' + type + '"' +
            // --ig-node-stripe drives the inset coloured stripe
            // on the left edge of the pill (see CSS box-shadow).
            // border-color matches so the 2px outline is the
            // same hue as the stripe — keeps the pill's silhouette
            // type-coded even before the icon is read.
            ' style="--ig-node-stripe:' + color +
            '; border-color:' + color + ';">' +
                '<div class="ig-node-icon" style="color:' + color + ';">' +
                    icon +
                '</div>' +
                '<div class="ig-node-text">' +
                    '<div class="ig-node-title">' + escapeHtml(data.label || data.name || '') + '</div>' +
                    (subtitle
                        ? '<div class="ig-node-subtitle">' + escapeHtml(subtitle) + '</div>'
                        : '') +
                '</div>' +
                bubble +
            '</div>'
        );
    }

    // ── INTERACTIONS ────────────────────────────────────────

    function wireGraphInteractions() {
        // Colour annotation has to happen before the first
        // render so the border-data style binding has a value
        // to read. Doing it lazily inside the layout chain.
        cy.nodes().forEach(n => {
            // Real nodes get the type colour; anything Cytoscape
            // somehow created without a known node_type gets a
            // transparent border so it doesn't render as a
            // visible empty box (defensive — should not happen
            // with our data, but sub-millisecond cost).
            n.data('borderColor',
                TYPE_COLOR[n.data('node_type')] || 'transparent');
        });

        // Single click → highlight node + its first-degree
        // neighbours (no transitive walk). Click on background
        // → clear selection.
        cy.on('tap', 'node', evt => {
            selectNode(evt.target.id());
        });
        cy.on('tap', evt => {
            if (evt.target === cy) clearSelection();
        });

        // Double click → open the detail page in a NEW tab so
        // the graph view stays put (operators are usually
        // exploring relationships, not navigating away). The
        // 'noopener,noreferrer' window features keep the new
        // tab from gaining a back-reference to this window.
        cy.on('dbltap', 'node', evt => {
            const url = evt.target.data('detail_url');
            if (url) window.open(url, '_blank', 'noopener,noreferrer');
        });

        // Hover tooltip — content built from the node's data.
        cy.on('mouseover', 'node', evt => {
            showTooltip(evt.target, evt.originalEvent);
        });
        cy.on('mouseout', 'node', () => hideTooltip());
        cy.on('pan zoom', () => hideTooltip());
    }

    function selectNode(nodeId) {
        if (!cy) return;
        selectedNodeId = nodeId;
        const node = cy.getElementById(nodeId);
        if (!node || !node.length) return;

        const neighborhood = node.closedNeighborhood();
        cy.elements().addClass('faded');
        neighborhood.removeClass('faded').addClass('highlighted');

        writeUrlState();
    }

    function clearSelection() {
        if (!cy) return;
        selectedNodeId = null;
        cy.elements().removeClass('faded highlighted');
        writeUrlState();
    }

    // ── TOOLTIP ─────────────────────────────────────────────

    function showTooltip(node, originalEvent) {
        const tip = document.getElementById('inventory-graph-tooltip');
        if (!tip) return;
        const d = node.data();
        const rows = [];

        rows.push(['Type', TYPE_LABEL[d.node_type] || d.node_type]);
        if (d.version)         rows.push(['Version', d.version]);
        if (d.materiality)     rows.push(['Materiality', d.materiality]);
        if (d.domain)          rows.push(['Domain', d.domain]);
        if (d.owner)           rows.push(['Owner', d.owner]);
        if (d.config_name)     rows.push(['Config', d.config_name]);
        if (d.model)           rows.push(['Model', d.model]);
        if (d.governance_tier) rows.push(['Tier', d.governance_tier]);
        if (d.api_role)        rows.push(['Role', d.api_role]);
        if (d.transport)       rows.push(['Transport', d.transport]);
        if (d.mcp_server_name) rows.push(['MCP server', d.mcp_server_name]);
        if (typeof d.decision_count_30d === 'number') {
            rows.push(['Decisions (30d)', d.decision_count_30d.toLocaleString()]);
        }
        if (typeof d.validation_passed === 'boolean') {
            rows.push(['Last validation',
                d.validation_passed ? 'passed' : 'failed']);
        }

        tip.innerHTML =
            '<div class="ig-tooltip-title">' +
                escapeHtml(d.label || d.name || '') +
            '</div>' +
            '<table class="ig-tooltip-table">' +
                rows.map(r =>
                    '<tr><th>' + escapeHtml(r[0]) + '</th>' +
                    '<td>' + escapeHtml(String(r[1])) + '</td></tr>')
                    .join('') +
            '</table>' +
            (d.detail_url
                ? '<div class="ig-tooltip-foot">Double-click to open in new tab</div>'
                : '');

        const x = (originalEvent && originalEvent.clientX) || 0;
        const y = (originalEvent && originalEvent.clientY) || 0;
        tip.style.left = (x + 16) + 'px';
        tip.style.top  = (y + 16) + 'px';
        tip.hidden = false;
    }

    function hideTooltip() {
        const tip = document.getElementById('inventory-graph-tooltip');
        if (tip) tip.hidden = true;
    }

    // ── CONTROL BAR ─────────────────────────────────────────

    function populateAppFilter(apps) {
        const host = document.getElementById('app-filter-options');
        if (!host) return;
        host.innerHTML = apps.map(app =>
            '<label class="ig-filter-item">' +
                '<input type="checkbox" value="' + escapeHtml(app.id) +
                '" data-app-name="' + escapeHtml(app.name) + '" checked>' +
                escapeHtml(app.label) +
            '</label>'
        ).join('');
    }

    // ── LEGEND / NODE-TYPE TOGGLES ──────────────────────────
    //
    // The Show panel doubles as a legend. Each entry in
    // LEGEND_ENTRIES becomes one row: a checkbox to toggle
    // visibility for that type, a colour swatch, the same
    // Unicode glyph used inside the node, and the type label.
    // Edges aren't toggleable separately — they follow whether
    // both their endpoint nodes are currently visible.

    const LEGEND_ENTRIES = [
        { type: 'agent',  label: 'Agents'  },
        { type: 'task',   label: 'Tasks'   },
        { type: 'prompt', label: 'Prompts' },
        { type: 'config', label: 'Configs' },
        { type: 'tool',   label: 'Tools'   },
    ];

    function renderLegend() {
        const host = document.getElementById('node-type-legend');
        if (!host) return;
        host.innerHTML = LEGEND_ENTRIES.map(e => {
            const color = TYPE_COLOR[e.type];
            const glyph = ICONS[e.type] || '';
            return (
                '<label class="ig-legend-row">' +
                    '<input type="checkbox" data-node-type="' +
                        e.type + '" checked>' +
                    '<span class="ig-legend-swatch"' +
                        ' style="background:' + color + ';"></span>' +
                    '<span class="ig-legend-glyph"' +
                        ' style="color:' + color + ';">' + glyph + '</span>' +
                    '<span class="ig-legend-label">' +
                        escapeHtml(e.label) + '</span>' +
                '</label>'
            );
        }).join('');
    }

    function wireControlBar() {
        document.getElementById('app-filter-options')?.addEventListener(
            'change', applyFilters);
        // Single delegated listener on the legend host: every
        // checkbox change inside it re-applies filters.
        document.getElementById('node-type-legend')?.addEventListener(
            'change', applyFilters);
        document.getElementById('reset-view')?.addEventListener(
            'click', () => {
                clearSelection();
                cy.fit(undefined, 60);
            });
    }

    function getSelectedApps() {
        const checked = Array.from(
            document.querySelectorAll('#app-filter-options input:checked'),
        );
        return checked.map(c => c.value);
    }

    function getNodeTypeToggles() {
        // Returns { agent: bool, task: bool, prompt: bool,
        // config: bool, tool: bool }. Defaults to all-true if
        // the legend hasn't rendered yet.
        const out = {
            agent: true, task: true, prompt: true,
            config: true, tool: true,
        };
        document.querySelectorAll(
            '#node-type-legend input[data-node-type]'
        ).forEach(cb => {
            out[cb.dataset.nodeType] = !!cb.checked;
        });
        return out;
    }

    function applyFilters() {
        if (!cy) return;
        const selectedApps = new Set(getSelectedApps());
        const allAppCount  = allApplications.length;
        const allSelected  = selectedApps.size === allAppCount;
        const types        = getNodeTypeToggles();

        // Update the dropdown summary label (shows counts).
        const summary = document.querySelector('#app-filter-dropdown summary');
        if (summary) {
            summary.textContent = allSelected
                ? 'All applications'
                : (selectedApps.size + ' of ' + allAppCount + ' applications');
        }

        // Hide nodes whose type is toggled off OR whose app
        // list does not intersect the selected apps. Configs
        // without an inherited application set (empty list)
        // remain visible only when "all applications" is on.
        //
        // Two channels per node:
        //   * .hidden class → drives Cytoscape's display:none
        //     style on the underlying node (and its incident
        //     edges); takes the geometry out of layout.
        //   * data.hidden → drives the HTML-label overlay via
        //     nodeHtmlLabel(). The plugin re-renders the
        //     template on data change, so flipping data.hidden
        //     swaps the visible card to an empty placeholder.
        // Without BOTH channels the overlay sticks around even
        // when the underlying node is gone.
        cy.batch(() => {
            cy.nodes().forEach(n => {
                const t = n.data('node_type');
                const typeOk = types[t] !== false;

                let appOk = allSelected;
                if (!appOk) {
                    const apps = n.data('applications') || [];
                    appOk = apps.some(a => selectedApps.has(a));
                }
                const isHidden = !(typeOk && appOk);
                n.toggleClass('hidden', isHidden);
                // Only write data when it actually changes —
                // avoids needless overlay re-renders.
                if (n.data('hidden') !== isHidden) {
                    n.data('hidden', isHidden);
                }
            });

            // Edges always follow node visibility — show iff
            // both endpoints are visible.
            cy.edges().forEach(e => {
                const src = cy.getElementById(e.data('source'));
                const tgt = cy.getElementById(e.data('target'));
                const endpointsVisible =
                    src && src.length && !src.hasClass('hidden') &&
                    tgt && tgt.length && !tgt.hasClass('hidden');
                e.toggleClass('hidden', !endpointsVisible);
            });
        });

        writeUrlState();
    }

    // ── URL STATE ───────────────────────────────────────────

    function writeUrlState() {
        const params = new URLSearchParams();
        const types  = getNodeTypeToggles();

        // Apps: serialize as ?app=name1,name2 (using app names
        // not UUIDs — names are stable + readable).
        const checkedNames = Array.from(
            document.querySelectorAll('#app-filter-options input:checked'),
        ).map(c => c.dataset.appName);
        if (checkedNames.length &&
                checkedNames.length < allApplications.length) {
            params.set('app', checkedNames.join(','));
        }

        // Node-type toggles: serialise the OFF set since
        // defaults are all-on. e.g. ?hide=configs,tools.
        const off = [];
        for (const k of ['agent', 'task', 'prompt', 'config', 'tool']) {
            if (!types[k]) off.push(k + 's');  // pluralise for readability
        }
        if (off.length) params.set('hide', off.join(','));

        if (selectedNodeId) params.set('selected', selectedNodeId);

        const next = params.toString();
        const url = window.location.pathname + (next ? '?' + next : '');
        window.history.replaceState(null, '', url);
    }

    function applyUrlState() {
        const params = new URLSearchParams(window.location.search);

        // Apps: restore by name (matches the serialiser).
        const appsParam = params.get('app');
        if (appsParam) {
            const wanted = new Set(appsParam.split(',').filter(Boolean));
            document.querySelectorAll('#app-filter-options input').forEach(
                c => { c.checked = wanted.has(c.dataset.appName); });
        }

        // Node-type toggles: anything in the hide set turns off.
        // The serialiser uses pluralised names ('agents','tasks',
        // 'prompts','configs','tools') for readability.
        const off = (params.get('hide') || '').split(',').filter(Boolean);
        const offSet = new Set(off);
        document.querySelectorAll(
            '#node-type-legend input[data-node-type]'
        ).forEach(cb => {
            // Same pluralisation as writeUrlState (agent →
            // agents, etc.) — the URL is human-readable.
            const plural = cb.dataset.nodeType + 's';
            if (offSet.has(plural)) cb.checked = false;
        });

        // Selected node: restore highlight after Cytoscape has
        // its first frame. Done in the caller after init().
        const sel = params.get('selected');
        if (sel) selectedNodeId = sel;
    }

    // ── HELPERS ─────────────────────────────────────────────

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;',
            '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    function shortNumber(n) {
        // 1.2k / 18k / 142 — keeps the bubble compact.
        if (n >= 1000) {
            return (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k';
        }
        return String(n);
    }

    // ── BOOT ────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

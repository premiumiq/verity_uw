-- Named queries for the L3 compliance metamodel.
-- Used by /admin/compliance/* admin web pages.
--
-- Architecture: docs/architecture/compliance-stack.md


-- name: list_compliance_frameworks_for_matrix
-- Column headers for the coverage matrix, ordered by sort_seq.
-- Excludes any framework whose validity has expired.
SELECT id, code, name, jurisdiction, version, sort_seq
FROM verity_compliance.regulatory_framework
WHERE valid_to >= current_date
ORDER BY sort_seq, code;


-- name: list_compliance_themes
-- All canonical_requirement_themes for grouping matrix rows.
SELECT id, code, name, description, sort_seq
FROM verity_compliance.canonical_requirement_theme
ORDER BY sort_seq, code;


-- name: list_canonical_requirements_with_bridges
-- One row per canonical_requirement, with a JSON aggregate of all
-- framework bridges (provision_requirement_map joins) so the matrix
-- view can render canonical × framework cells.
--
-- The `bridges` array contains one entry per (framework × canonical)
-- pair where ≥1 provision in that framework links to this canonical.
-- Strongest match_strength wins when multiple provisions in the same
-- framework all bridge to the same canonical.
SELECT
    cr.id           AS canonical_id,
    cr.code         AS canonical_code,
    cr.title        AS canonical_title,
    cr.description  AS canonical_description,
    cr.sort_seq     AS canonical_sort,
    t.code          AS theme_code,
    t.name          AS theme_name,
    t.sort_seq      AS theme_sort,
    cov.coverage_level,
    cov.rationale,
    cov.customer_actions,
    COALESCE(
        (
            SELECT json_agg(b ORDER BY b->>'framework_sort')
            FROM (
                SELECT json_build_object(
                    'framework_code', f.code,
                    'framework_name', f.name,
                    'framework_sort', f.sort_seq,
                    'best_match_strength', MAX(prm.match_strength),
                    'provision_count', COUNT(*)
                ) AS b,
                f.sort_seq
                FROM verity_compliance.provision_requirement_map prm
                JOIN verity_compliance.regulatory_provision  p ON p.id = prm.provision_id
                JOIN verity_compliance.regulatory_framework  f ON f.id = p.framework_id
                WHERE prm.canonical_requirement_id = cr.id
                GROUP BY f.id, f.code, f.name, f.sort_seq
            ) sub
        ),
        '[]'::json
    ) AS bridges
FROM       verity_compliance.canonical_requirement cr
JOIN       verity_compliance.canonical_requirement_theme t   ON t.id   = cr.theme_id
LEFT JOIN  verity_compliance.requirement_coverage          cov ON cov.canonical_requirement_id = cr.id
ORDER BY t.sort_seq, cr.sort_seq, cr.code;


-- name: get_canonical_requirement_by_code
-- Drilldown: full detail for one canonical_requirement.
-- (Bridges and feature_links are fetched separately so the template
--  can render distinct sections cleanly.)
SELECT
    cr.id, cr.code, cr.title, cr.description, cr.sort_seq,
    t.code AS theme_code,
    t.name AS theme_name,
    cov.coverage_level,
    cov.rationale,
    cov.customer_actions,
    cov.last_reviewed_at,
    cov.reviewed_by
FROM       verity_compliance.canonical_requirement cr
JOIN       verity_compliance.canonical_requirement_theme t  ON t.id  = cr.theme_id
LEFT JOIN  verity_compliance.requirement_coverage         cov ON cov.canonical_requirement_id = cr.id
WHERE cr.code = %(canonical_code)s;


-- name: list_provisions_for_canonical
-- All provisions that bridge to one canonical requirement.
SELECT
    p.id              AS provision_id,
    p.citation,
    p.title           AS provision_title,
    p.text            AS provision_text,
    f.code            AS framework_code,
    f.name            AS framework_name,
    f.jurisdiction,
    prm.match_strength,
    prm.confidence,
    prm.mapping_source,
    prm.notes
FROM       verity_compliance.provision_requirement_map prm
JOIN       verity_compliance.regulatory_provision      p   ON p.id   = prm.provision_id
JOIN       verity_compliance.regulatory_framework      f   ON f.id   = p.framework_id
JOIN       verity_compliance.canonical_requirement     cr  ON cr.id  = prm.canonical_requirement_id
WHERE cr.code = %(canonical_code)s
ORDER BY f.sort_seq, p.sort_seq, p.citation;


-- name: list_features_for_canonical
-- All Verity features linked to one canonical requirement.
SELECT
    feat.id           AS feature_id,
    feat.code         AS feature_code,
    feat.name         AS feature_name,
    feat.description  AS feature_description,
    feat.status,
    cap.code          AS capability_code,
    cap.name          AS capability_name,
    plane.code        AS plane_code,
    plane.name        AS plane_name,
    rfl.role,
    rfl.notes         AS link_notes
FROM       verity_compliance.requirement_feature_link rfl
JOIN       verity_compliance.feature                 feat  ON feat.id  = rfl.feature_id
JOIN       verity_compliance.feature_capability      cap   ON cap.id   = feat.capability_id
JOIN       verity_compliance.feature_plane           plane ON plane.id = cap.plane_id
JOIN       verity_compliance.canonical_requirement   cr    ON cr.id    = rfl.canonical_requirement_id
WHERE cr.code = %(canonical_code)s
ORDER BY rfl.role DESC, plane.sort_seq, cap.sort_seq, feat.sort_seq;


-- name: get_provision_by_id
-- Drilldown for one provision: text + framework + bridges to canonicals.
SELECT
    p.id, p.citation, p.title, p.text, p.sort_seq,
    p.valid_from, p.valid_to,
    f.code         AS framework_code,
    f.name         AS framework_name,
    f.jurisdiction
FROM       verity_compliance.regulatory_provision p
JOIN       verity_compliance.regulatory_framework f ON f.id = p.framework_id
WHERE p.id = %(provision_id)s;


-- name: list_canonicals_for_provision
-- Reverse drilldown: all canonical_requirements bridged to one provision.
SELECT
    cr.id            AS canonical_id,
    cr.code          AS canonical_code,
    cr.title         AS canonical_title,
    cr.description   AS canonical_description,
    cov.coverage_level,
    prm.match_strength,
    prm.confidence,
    prm.mapping_source,
    t.code           AS theme_code,
    t.name           AS theme_name
FROM       verity_compliance.provision_requirement_map prm
JOIN       verity_compliance.canonical_requirement     cr   ON cr.id  = prm.canonical_requirement_id
JOIN       verity_compliance.canonical_requirement_theme t  ON t.id   = cr.theme_id
LEFT JOIN  verity_compliance.requirement_coverage         cov ON cov.canonical_requirement_id = cr.id
WHERE prm.provision_id = %(provision_id)s
ORDER BY prm.match_strength DESC, t.sort_seq, cr.sort_seq;


-- name: compliance_coverage_rollup
-- Counts of canonicals per coverage level — for the rollup card on the matrix page.
SELECT
    coverage_level,
    COUNT(*) AS canonical_count
FROM verity_compliance.requirement_coverage
GROUP BY coverage_level;


-- name: compliance_overall_counts
-- Top-level entity totals — for overview page header card.
SELECT
    (SELECT COUNT(*) FROM verity_compliance.regulatory_framework        WHERE valid_to >= current_date) AS framework_count,
    (SELECT COUNT(*) FROM verity_compliance.regulatory_provision)        AS provision_count,
    (SELECT COUNT(*) FROM verity_compliance.canonical_requirement_theme) AS theme_count,
    (SELECT COUNT(*) FROM verity_compliance.canonical_requirement)       AS canonical_count,
    (SELECT COUNT(*) FROM verity_compliance.feature_plane)               AS plane_count,
    (SELECT COUNT(*) FROM verity_compliance.feature_capability)          AS capability_count,
    (SELECT COUNT(*) FROM verity_compliance.feature)                     AS feature_count,
    (SELECT COUNT(*) FROM verity_compliance.provision_requirement_map)   AS provision_canonical_bridges,
    (SELECT COUNT(*) FROM verity_compliance.requirement_feature_link)    AS canonical_feature_bridges;


-- name: list_frameworks_with_stats
-- Frameworks list page: per-framework provision count + distinct canonical count.
SELECT
    f.id, f.code, f.name, f.jurisdiction, f.version, f.effective_date,
    f.valid_from, f.valid_to, f.source_url, f.description, f.sort_seq,
    (SELECT COUNT(*) FROM verity_compliance.regulatory_provision p WHERE p.framework_id = f.id)
        AS provision_count,
    (SELECT COUNT(DISTINCT prm.canonical_requirement_id)
       FROM verity_compliance.regulatory_provision p
       JOIN verity_compliance.provision_requirement_map prm ON prm.provision_id = p.id
       WHERE p.framework_id = f.id)
        AS canonical_count
FROM verity_compliance.regulatory_framework f
ORDER BY f.sort_seq, f.code;


-- name: get_framework_by_code
SELECT id, code, name, jurisdiction, version, effective_date,
       valid_from, valid_to, source_url, description, sort_seq
FROM verity_compliance.regulatory_framework
WHERE code = %(framework_code)s;


-- name: list_provisions_for_framework
-- All provisions in one framework, with bridge counts.
SELECT
    p.id, p.citation, p.title, p.text, p.sort_seq,
    p.valid_from, p.valid_to,
    (SELECT COUNT(*) FROM verity_compliance.provision_requirement_map prm
        WHERE prm.provision_id = p.id) AS canonical_link_count
FROM       verity_compliance.regulatory_provision p
JOIN       verity_compliance.regulatory_framework f ON f.id = p.framework_id
WHERE f.code = %(framework_code)s
ORDER BY p.sort_seq, p.citation;


-- name: list_canonicals_grouped
-- Canonical requirements list page: theme + canonical + coverage + counts.
SELECT
    cr.id, cr.code, cr.title, cr.description, cr.sort_seq,
    t.code AS theme_code,
    t.name AS theme_name,
    t.sort_seq AS theme_sort,
    cov.coverage_level,
    cov.rationale,
    cov.customer_actions,
    (SELECT COUNT(*) FROM verity_compliance.provision_requirement_map prm
        WHERE prm.canonical_requirement_id = cr.id) AS provision_count,
    (SELECT COUNT(*) FROM verity_compliance.requirement_feature_link rfl
        WHERE rfl.canonical_requirement_id = cr.id) AS feature_count
FROM       verity_compliance.canonical_requirement cr
JOIN       verity_compliance.canonical_requirement_theme t   ON t.id  = cr.theme_id
LEFT JOIN  verity_compliance.requirement_coverage          cov ON cov.canonical_requirement_id = cr.id
ORDER BY t.sort_seq, cr.sort_seq, cr.code;


-- name: list_features_grouped
-- Engineering hierarchy view: plane → capability → feature, with canonical link counts.
SELECT
    plane.code AS plane_code, plane.name AS plane_name, plane.sort_seq AS plane_sort,
    cap.code   AS capability_code, cap.name AS capability_name, cap.sort_seq AS capability_sort,
    feat.id, feat.code AS feature_code, feat.name AS feature_name,
    feat.description AS feature_description, feat.status, feat.sort_seq AS feature_sort,
    (SELECT COUNT(*) FROM verity_compliance.requirement_feature_link rfl
        WHERE rfl.feature_id = feat.id) AS canonical_link_count
FROM       verity_compliance.feature_plane plane
JOIN       verity_compliance.feature_capability cap ON cap.plane_id = plane.id
JOIN       verity_compliance.feature             feat ON feat.capability_id = cap.id
ORDER BY plane.sort_seq, cap.sort_seq, feat.sort_seq;


-- name: get_feature_by_code
SELECT
    feat.id, feat.code, feat.name, feat.description, feat.status, feat.sort_seq,
    cap.code  AS capability_code, cap.name  AS capability_name,
    plane.code AS plane_code, plane.name AS plane_name
FROM       verity_compliance.feature feat
JOIN       verity_compliance.feature_capability cap ON cap.id = feat.capability_id
JOIN       verity_compliance.feature_plane     plane ON plane.id = cap.plane_id
WHERE feat.code = %(feature_code)s;


-- name: list_canonicals_for_feature
-- Reverse drilldown: which canonical requirements does this feature support?
SELECT
    cr.id   AS canonical_id,
    cr.code AS canonical_code,
    cr.title AS canonical_title,
    cr.description AS canonical_description,
    t.code AS theme_code, t.name AS theme_name,
    cov.coverage_level,
    rfl.role,
    rfl.notes AS link_notes
FROM       verity_compliance.requirement_feature_link rfl
JOIN       verity_compliance.canonical_requirement cr  ON cr.id = rfl.canonical_requirement_id
JOIN       verity_compliance.canonical_requirement_theme t ON t.id = cr.theme_id
LEFT JOIN  verity_compliance.requirement_coverage cov  ON cov.canonical_requirement_id = cr.id
JOIN       verity_compliance.feature feat ON feat.id = rfl.feature_id
WHERE feat.code = %(feature_code)s
ORDER BY rfl.role DESC, t.sort_seq, cr.sort_seq;


-- name: list_provision_canonical_bridges
-- Filterable table of every provision↔canonical bridge for the Bridges page.
-- Filters all use NULL-skip pattern: NULL means "no filter".
SELECT
    prm.id            AS bridge_id,
    p.id              AS provision_id,
    p.citation,
    p.title           AS provision_title,
    f.code            AS framework_code,
    f.name            AS framework_name,
    cr.id             AS canonical_id,
    cr.code           AS canonical_code,
    cr.title          AS canonical_title,
    t.code            AS theme_code,
    prm.match_strength,
    prm.confidence,
    prm.mapping_source,
    prm.validated_by,
    prm.validated_at
FROM       verity_compliance.provision_requirement_map prm
JOIN       verity_compliance.regulatory_provision      p   ON p.id = prm.provision_id
JOIN       verity_compliance.regulatory_framework      f   ON f.id = p.framework_id
JOIN       verity_compliance.canonical_requirement     cr  ON cr.id = prm.canonical_requirement_id
JOIN       verity_compliance.canonical_requirement_theme t ON t.id = cr.theme_id
WHERE (%(framework_code)s::text    IS NULL OR f.code  = %(framework_code)s)
  AND (%(canonical_code)s::text    IS NULL OR cr.code = %(canonical_code)s)
  AND (%(mapping_source)s::text    IS NULL OR prm.mapping_source = %(mapping_source)s)
  AND (%(min_match_strength)s::numeric IS NULL OR prm.match_strength >= %(min_match_strength)s)
ORDER BY f.sort_seq, p.sort_seq, prm.match_strength DESC;


-- name: list_active_reports
-- Reports list page. Includes canonical-coverage counts per report so the
-- card UI can show "this report evidences N canonical requirements".
SELECT
    rd.id, rd.code, rd.name, rd.description, rd.report_kind,
    rd.docx_template, rd.output_formats, rd.scope_params,
    rd.sort_seq, rd.is_active, rd.created_at,
    (SELECT COUNT(*) FROM verity_compliance.report_requirement rr
        WHERE rr.report_id = rd.id) AS canonical_count
FROM verity_compliance.report_definition rd
WHERE rd.is_active = true
ORDER BY rd.sort_seq, rd.code;


-- name: list_recent_report_runs
-- Audit trail card on the report list page (most recent runs across all reports).
SELECT
    rrl.id, rrl.report_id, rrl.requested_by, rrl.scope_params,
    rrl.output_formats, rrl.status, rrl.duration_ms,
    rrl.created_at, rrl.completed_at,
    rd.code  AS report_code,
    rd.name  AS report_name
FROM       verity_compliance.report_run_log rrl
JOIN       verity_compliance.report_definition rd ON rd.id = rrl.report_id
ORDER BY rrl.created_at DESC
LIMIT 25;


-- name: list_reports_for_canonical
-- Reverse lookup: which active reports provide evidence for this canonical?
-- Used on the canonical detail page to surface the "evidence pathway".
SELECT
    rd.id, rd.code, rd.name, rd.description,
    rd.report_kind, rd.output_formats,
    rr.section, rr.sort_seq AS requirement_sort
FROM       verity_compliance.canonical_requirement cr
JOIN       verity_compliance.report_requirement   rr ON rr.canonical_requirement_id = cr.id
JOIN       verity_compliance.report_definition    rd ON rd.id = rr.report_id
WHERE cr.code = %(canonical_code)s
  AND rd.is_active = true
ORDER BY rd.sort_seq, rd.code;


-- name: list_canonical_feature_bridges
-- Filterable table of every canonical↔feature link for the Bridges page (second tab).
SELECT
    rfl.id            AS bridge_id,
    cr.id             AS canonical_id,
    cr.code           AS canonical_code,
    cr.title          AS canonical_title,
    t.code            AS theme_code,
    feat.id           AS feature_id,
    feat.code         AS feature_code,
    feat.name         AS feature_name,
    feat.status,
    cap.code          AS capability_code,
    plane.code        AS plane_code,
    rfl.role,
    rfl.notes
FROM       verity_compliance.requirement_feature_link rfl
JOIN       verity_compliance.canonical_requirement cr     ON cr.id = rfl.canonical_requirement_id
JOIN       verity_compliance.canonical_requirement_theme t ON t.id = cr.theme_id
JOIN       verity_compliance.feature feat                 ON feat.id = rfl.feature_id
JOIN       verity_compliance.feature_capability cap       ON cap.id = feat.capability_id
JOIN       verity_compliance.feature_plane plane          ON plane.id = cap.plane_id
WHERE (%(canonical_code)s::text IS NULL OR cr.code   = %(canonical_code)s)
  AND (%(feature_code)s::text   IS NULL OR feat.code = %(feature_code)s)
  AND (%(plane_code)s::text     IS NULL OR plane.code = %(plane_code)s)
  AND (%(role)s::text           IS NULL OR rfl.role  = %(role)s)
ORDER BY t.sort_seq, cr.sort_seq, rfl.role DESC, plane.sort_seq, cap.sort_seq;

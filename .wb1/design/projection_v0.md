# Projection V0 (from verdict 5553019807)

- SOURCE_OF_TRUTH=GitHub/NAS/runtime
- PROJECTION=append-only cache, rebuildable
- 8501=read projection
- A_PATH=manual/periodic refresh + rebuild fallback
- NO_NEW_COMPLEX_INFRA=YES
- ROLLBACK=delete projection, fall back to A
- 每条事件保留 EVIDENCE_REF 指回 GitHub/NAS

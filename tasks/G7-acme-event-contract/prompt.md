Implement `AcmeOrderEventService.handle_request` in `acme_orders/handler.py` for the internal Acme Order Ingestion service so it complies strictly with Acme's internal engineering standards.

Requirements summary:
1. Explore the repository and read `docs/` (`docs/README.md` and linked documentation) before implementing. Pay careful attention to active canonical engineering specifications versus deprecated or unrelated operational notes.
2. Persist accepted records via `acme_orders/storage.py` (`OrderStorage`) and emit responses using `HttpResponse` in `acme_orders/models.py`.
3. Follow Acme's active contracts for inbound order validation, request correlation and concurrency controls, structured responses, persistence, and compliance logging.
4. Write unit and contract tests under `tests/` and run `pytest` after your final edits to confirm all checks pass.

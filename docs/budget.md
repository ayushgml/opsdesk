# Budget ledger

Budget reservations are shared by file path. Keep that file on a local filesystem supporting advisory locks. A request with unknown usage marks billing uncertain and blocks new reservations. Reconcile the provider record before clearing uncertainty; interrupted processes may leave reservations that also need reconciliation.

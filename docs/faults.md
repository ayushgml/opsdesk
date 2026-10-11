# Mock tool faults

Use a fault rule with `tool`, optional canonical `service`, and either `failures` or `sequence`. For example, `{"tool":"get_metrics","service":"api","sequence":["timeout","failed"]}` fails the first two matching attempts. Explicit sequences take precedence over generated fault types.

"""Qt-free backend service for the native desktop app (NATIVE-DESKTOP-PLAN.md
section 4.4).

The C++ app (desktop/) keeps GUI-side computations in Python -- one
implementation of every function -- by calling this service over a
process boundary: JSON-RPC 2.0, one JSON object per line, on
stdin/stdout.

    python -m backend_service

Every method wraps an EXISTING function; none re-implements anything.
The conformance gate (gui/tests/test_backend_service.py) requires each
method's RPC result to equal the direct Python call.
"""

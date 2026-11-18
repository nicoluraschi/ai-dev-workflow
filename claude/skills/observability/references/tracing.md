# Distributed Tracing — OpenTelemetry

Load this file when the feature crosses service boundaries (microservices, external APIs that you own, worker ↔ web communication).

For single-service monoliths, Sentry's performance tracing (via `traces_sample_rate`) is usually sufficient — skip this file.

---

## When to Apply Distributed Tracing

Apply OpenTelemetry spans when:
- A user request fans out to multiple internal services
- A background job is triggered by a web request and you want to correlate the two
- You own multiple services and need end-to-end latency visibility
- An operation's duration spans an async boundary (enqueue → dequeue → complete)

Do NOT over-instrument: a single Rails monolith with Sentry performance tracing does not need manual OTel spans on every method call.

---

## Core Concepts

```
Trace: the full journey of one request across all services
  └── Span: one unit of work within a trace
        ├── has a name, start time, duration
        ├── has attributes (key-value metadata)
        └── has a status (OK / ERROR)

Trace context propagates via HTTP headers:
  traceparent: 00-{trace_id}-{span_id}-{flags}
```

---

## Instrumentation Pattern (language-agnostic)

### What to instrument

1. **Service entry points** — HTTP handlers, job handlers, message consumers
2. **External calls** — outbound HTTP, database queries (if not auto-instrumented), queue publishes
3. **Significant internal operations** — file processing, report generation, data transformations > ~100ms

### What NOT to instrument manually

- Simple getters/setters
- In-memory operations that complete in < 1ms
- Anything auto-instrumented by the SDK (most HTTP clients, DB drivers)

### Span naming convention

```
<component>.<operation>
Examples:
  http.request          (outbound HTTP)
  db.query              (database)
  job.process           (background job)
  payment.charge        (business operation)
  file.import           (data operation)
```

### Attributes to set on every span

```
service.name        → your app name
deployment.environment → production / staging
user.id             → authenticated user (if applicable)
```

### Attributes to set per span type

```
HTTP handler span:
  http.method, http.route, http.status_code

Outbound HTTP span:
  http.url (sanitized — no tokens in URL), http.method, http.status_code

DB span:
  db.system (postgresql, mysql, redis), db.operation (SELECT, INSERT)
  db.statement (sanitized — no user values inline)

Job span:
  messaging.system (solid_queue, sidekiq), job.class, job.id
```

---

## Ruby (opentelemetry-ruby)

```ruby
# Gemfile
gem 'opentelemetry-sdk'
gem 'opentelemetry-instrumentation-rails'
gem 'opentelemetry-instrumentation-active_record'
gem 'opentelemetry-instrumentation-http'
gem 'opentelemetry-exporter-otlp'

# config/initializers/opentelemetry.rb
OpenTelemetry::SDK.configure do |c|
  c.service_name = ENV.fetch('OTEL_SERVICE_NAME', 'my-app')
  c.use_all  # auto-instruments Rails, AR, Net::HTTP
end

# Manual span for a significant operation
tracer = OpenTelemetry.tracer_provider.tracer('my-app')
tracer.in_span('payment.charge', attributes: { 'order.id' => order.id.to_s }) do |span|
  result = stripe.charge(...)
  span.set_attribute('payment.provider', 'stripe')
  span.set_attribute('payment.status', result.status)
rescue => e
  span.record_exception(e)
  span.status = OpenTelemetry::Trace::Status.error(e.message)
  raise
end
```

---

## Node.js (@opentelemetry/sdk-node)

```typescript
// instrumentation.ts — loaded before everything else
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';
import { getNodeAutoInstrumentations } from '@opentelemetry/auto-instrumentations-node';

const sdk = new NodeSDK({
  serviceName: process.env.OTEL_SERVICE_NAME ?? 'my-app',
  traceExporter: new OTLPTraceExporter(),
  instrumentations: [getNodeAutoInstrumentations()],
});
sdk.start();

// Manual span
import { trace } from '@opentelemetry/api';
const tracer = trace.getTracer('my-app');

await tracer.startActiveSpan('payment.charge', async (span) => {
  try {
    const result = await stripe.charges.create(payload);
    span.setAttribute('payment.status', result.status);
  } catch (err) {
    span.recordException(err as Error);
    span.setStatus({ code: SpanStatusCode.ERROR });
    throw err;
  } finally {
    span.end();
  }
});
```

---

## Python (opentelemetry-python)

```python
# Auto-instrumentation at startup
opentelemetry-instrument \
  --service-name my-app \
  --exporter-otlp-endpoint http://otel-collector:4317 \
  python -m uvicorn app.main:app

# Manual span
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("payment.charge") as span:
    span.set_attribute("order.id", str(order_id))
    try:
        result = stripe.Charge.create(amount=amount, source=token)
        span.set_attribute("payment.status", result.status)
    except stripe.error.StripeError as e:
        span.record_exception(e)
        span.set_status(trace.StatusCode.ERROR, str(e))
        raise
```

---

## Trace Context Propagation

When a web request triggers a background job, propagate the trace context so both appear in the same trace:

```ruby
# Rails + Solid Queue example
# When enqueuing:
headers = {}
OpenTelemetry.propagation.inject(headers)
ImportJob.perform_later(import_id, trace_context: headers)

# In the job:
def perform(import_id, trace_context: {})
  OpenTelemetry.propagation.extract(trace_context)
  tracer.in_span('job.import') do
    # now this span is a child of the original request span
  end
end
```

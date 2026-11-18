# Sentry Integration Patterns

Loaded when the project uses Sentry for error tracking. Apply the relevant section for the detected stack.

---

## Ruby on Rails (sentry-ruby + sentry-rails)

### Setup verification
```ruby
# config/initializers/sentry.rb
Sentry.init do |config|
  config.dsn = ENV['SENTRY_DSN']
  config.breadcrumbs_logger = [:active_support_logger, :http_logger]
  config.traces_sample_rate = 0.1  # 10% of transactions for performance
  config.send_default_pii = false  # never send PII by default
  config.environment = Rails.env
end
```

### Setting user context (do this in ApplicationController)
```ruby
before_action :set_sentry_context

def set_sentry_context
  return unless current_user
  Sentry.set_user(
    id: current_user.id,
    email: current_user.email  # only if acceptable per your privacy policy
  )
end
```

### Capturing exceptions with context
```ruby
# ❌ Silent rescue — Sentry never sees this
rescue StandardError => e
  Rails.logger.error("Something went wrong")
end

# ✅ Capture with context
rescue StandardError => e
  Sentry.capture_exception(e) do |scope|
    scope.set_tags(component: "payment", provider: "stripe")
    scope.set_context("order", { id: order.id, amount: order.amount_cents })
  end
  Rails.logger.error("Payment failed", error: e.message, order_id: order.id)
  raise  # or handle gracefully
end
```

### Background jobs (Solid Queue / Sidekiq / GoodJob)
```ruby
# sentry-rails handles job error capture automatically for ActiveJob
# For additional context per job:
class ImportJob < ApplicationJob
  def perform(import_id)
    Sentry.set_tags(job: self.class.name, import_id: import_id)
    # ... job body
  rescue => e
    Sentry.capture_exception(e) do |scope|
      scope.set_context("job", { import_id: import_id, attempt: executions })
    end
    raise
  end
end
```

### Breadcrumbs for complex flows
```ruby
# Add breadcrumbs before the risky operation so they appear in Sentry
Sentry.add_breadcrumb(Sentry::Breadcrumb.new(
  message: "Starting payment charge",
  category: "payment",
  data: { order_id: order.id, amount: order.amount_cents },
  level: "info"
))
```

### What to tag vs what to put in context
- **Tags** (indexed, filterable in Sentry UI): `environment`, `component`, `job_class`, `provider`, `plan`
- **Context** (rich data, not indexed): full request params, order details, API response bodies
- **User** (special field): `id`, optionally `email` — no passwords, tokens, or sensitive attributes

---

## Node.js / TypeScript (@sentry/node)

### Setup
```typescript
import * as Sentry from "@sentry/node";

Sentry.init({
  dsn: process.env.SENTRY_DSN,
  environment: process.env.NODE_ENV,
  tracesSampleRate: 0.1,
  sendDefaultPii: false,
});
```

### Express / Fastify middleware
```typescript
// Express — place BEFORE routes
app.use(Sentry.Handlers.requestHandler());
app.use(Sentry.Handlers.tracingHandler());

// Express — place AFTER all routes, BEFORE generic error handler
app.use(Sentry.Handlers.errorHandler());
```

### Setting user context
```typescript
// In auth middleware, after verifying the session
Sentry.setUser({ id: String(user.id), email: user.email });

// Clear on logout
Sentry.setUser(null);
```

### Manual capture with context
```typescript
try {
  await stripe.charges.create(payload);
} catch (err) {
  Sentry.withScope((scope) => {
    scope.setTag("component", "payment");
    scope.setTag("provider", "stripe");
    scope.setContext("charge", { orderId, amountCents });
    Sentry.captureException(err);
  });
  logger.error({ err, orderId }, "Payment charge failed");
  throw err;
}
```

### Background jobs / queues
```typescript
// Wrap job handler body
async function processJob(job: Job) {
  Sentry.withScope((scope) => {
    scope.setTag("job", job.name);
    scope.setContext("job_data", { id: job.id, attempt: job.attemptsMade });
  });
  try {
    await doWork(job.data);
  } catch (err) {
    Sentry.captureException(err);
    throw err;
  }
}
```

---

## Python (sentry-sdk)

### Setup (Django)
```python
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],
    integrations=[DjangoIntegration()],
    traces_sample_rate=0.1,
    send_default_pii=False,
    environment=os.environ.get("ENVIRONMENT", "development"),
)
```

### Setup (FastAPI)
```python
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration

sentry_sdk.init(
    dsn=os.environ["SENTRY_DSN"],
    integrations=[StarletteIntegration(), FastApiIntegration()],
    traces_sample_rate=0.1,
)
```

### User context
```python
with sentry_sdk.configure_scope() as scope:
    scope.set_user({"id": str(user.id), "email": user.email})
```

### Manual capture
```python
try:
    result = payment_provider.charge(amount, token)
except PaymentError as e:
    with sentry_sdk.push_scope() as scope:
        scope.set_tag("component", "payment")
        scope.set_context("charge", {"order_id": order_id, "amount": amount})
        sentry_sdk.capture_exception(e)
    logger.error("payment_failed", order_id=order_id, error=str(e))
    raise
```

### Celery / background tasks
```python
# sentry-sdk Celery integration captures task failures automatically
from sentry_sdk.integrations.celery import CeleryIntegration
sentry_sdk.init(..., integrations=[CeleryIntegration()])

# For additional context per task:
@app.task
def import_data(import_id: int):
    with sentry_sdk.configure_scope() as scope:
        scope.set_tag("task", "import_data")
        scope.set_context("task_args", {"import_id": import_id})
    # ... task body
```

---

## Common Mistakes to Avoid

| ❌ Anti-pattern | ✅ Fix |
|---|---|
| `rescue => e; nil; end` — silent swallow | Always capture or re-raise |
| Logging `e.message` only | Capture full exception with `capture_exception` |
| Capturing 404s and validation errors as errors | Use `capture_message` at `info` level or skip |
| Sending PII in context (passwords, tokens) | Scrub before sending; use `before_send` hook |
| Not setting user context | Set user in auth middleware, clear on logout |
| One generic "something went wrong" tag | Use specific component and operation tags |

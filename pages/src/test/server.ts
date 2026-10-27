import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

// The check page asks the scan server which builds it holds as soon as a file is
// loaded; tests that do not care about it get a fixed answer instead of an
// unhandled request.
export const server = setupServer(
  http.get('*/api/builds', () => HttpResponse.json({ builds: ['14192', '14191'] })),
)

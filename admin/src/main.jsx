import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntApp, ConfigProvider } from 'antd';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import App from './App.jsx';
import './assets/styles/main.scss';

// staleTime is not zero on purpose: the operator moves between the listing and
// an editor constantly, and refetching an unchanged catalogue on every hop is
// noise. Every mutation invalidates explicitly, so freshness comes from writes
// rather than from polling.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
  },
});

// basename="/admin" so react-router's paths and the served path agree. Change
// it here and in vite.config.js's `base` together, or the router will handle
// URLs the server never serves.
createRoot(document.getElementById('root')).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ConfigProvider>
        <AntApp>
          <BrowserRouter basename="/admin">
            <App />
          </BrowserRouter>
        </AntApp>
      </ConfigProvider>
    </QueryClientProvider>
  </StrictMode>,
);

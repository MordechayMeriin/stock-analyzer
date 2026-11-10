import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import './index.css'
import { ModeProvider } from './app/mode'
import { Layout } from './components/Layout'
import { Empty } from './components/states'
import { CompaniesPage } from './features/browser/CompaniesPage'
import { CompanyPage } from './features/browser/CompanyPage'
import { FinancialsPage } from './features/financials/FinancialsPage'
import { PlaygroundPage } from './features/playground/PlaygroundPage'
import { ReaderPage } from './features/reader/ReaderPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false, staleTime: 60_000 } },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    children: [
      { index: true, element: <CompaniesPage /> },
      { path: ':ticker', element: <CompanyPage /> },
      { path: ':ticker/financials', element: <FinancialsPage /> },
      { path: ':ticker/:fy/report', element: <ReaderPage /> },
      { path: ':ticker/:fy/report/:nodeId', element: <ReaderPage /> },
      { path: ':ticker/:fy/playground', element: <PlaygroundPage /> },
      { path: '*', element: <Empty title="הדף לא נמצא" /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ModeProvider>
        <RouterProvider router={router} />
      </ModeProvider>
    </QueryClientProvider>
  </StrictMode>,
)

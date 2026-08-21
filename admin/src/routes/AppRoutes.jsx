import { Navigate, Route, Routes } from 'react-router-dom';

import AdminLayout from '../components/layout/AdminLayout/AdminLayout.jsx';
import Categories from '../pages/Categories/Categories.jsx';
import Collections from '../pages/Collections/Collections.jsx';
import Login from '../pages/Login/Login.jsx';
import NotFound from '../pages/NotFound/NotFound.jsx';
import ProductEdit from '../pages/ProductEdit/ProductEdit.jsx';
import ProductNew from '../pages/ProductNew/ProductNew.jsx';
import Products from '../pages/Products/Products.jsx';
import OrderDetail from '../pages/OrderDetail/OrderDetail.jsx';
import Orders from '../pages/Orders/Orders.jsx';
import Promotions from '../pages/Promotions/Promotions.jsx';
import RequireAuth from './RequireAuth.jsx';

/**
 * Every route in one place, per the project structure document.
 *
 * The protected routes share a layout route so the chrome mounts once and the
 * gate is declared once -- adding a screen means adding a line here, not
 * remembering to wrap it.
 */
export default function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <RequireAuth>
            <AdminLayout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/products" replace />} />
        <Route path="/products" element={<Products />} />
        <Route path="/products/new" element={<ProductNew />} />
        <Route path="/products/:id" element={<ProductEdit />} />
        <Route path="/categories" element={<Categories />} />
        <Route path="/collections" element={<Collections />} />
        <Route path="/offers" element={<Promotions />} />
        <Route path="/orders" element={<Orders />} />
        <Route path="/orders/:orderNumber" element={<OrderDetail />} />
      </Route>
      <Route path="*" element={<NotFound />} />
    </Routes>
  );
}

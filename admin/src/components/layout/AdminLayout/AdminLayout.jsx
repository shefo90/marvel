import { Layout, Menu, Typography } from 'antd';
import { Link, Outlet, useLocation } from 'react-router-dom';

import { useAuth } from '../../../hooks/useAuth.js';
import styles from './AdminLayout.module.scss';

const ITEMS = [{ key: '/products', label: <Link to="/products">Products</Link> }];

/**
 * The chrome every protected screen sits inside.
 *
 * English only, left-to-right only -- a locked decision. Arabic appears in this
 * app only as *content* being edited, never as interface.
 */
export default function AdminLayout() {
  const { session, signOut } = useAuth();
  const location = useLocation();

  return (
    <Layout className={styles.shell}>
      <Layout.Sider breakpoint="lg" collapsedWidth="0" width={220}>
        <div className={styles.brand}>Marvel</div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname.startsWith('/products') ? '/products' : '']}
          items={ITEMS}
        />
      </Layout.Sider>
      <Layout>
        <Layout.Header className={styles.header}>
          <Typography.Text className={styles.actor}>
            {session?.user?.sub} · {session?.user?.role}
          </Typography.Text>
          <button type="button" className={styles.signOut} onClick={signOut}>
            Sign out
          </button>
        </Layout.Header>
        <Layout.Content className={`${styles.content} app-content`}>
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}

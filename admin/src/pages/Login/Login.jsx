import { Alert, Button, Card, Form, Input, Typography } from 'antd';
import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

import { useAuth } from '../../hooks/useAuth.js';
import { staffLogin } from '../../services/auth.service.js';
import styles from './Login.module.scss';

/**
 * Staff sign-in.
 *
 * Against `/api/en/auth/staff/login`. The `/en/` segment is cosmetic noise in
 * an unlocalized admin — open question 3 of the back-office design, left as it
 * is rather than duplicating auth routes to hide one path segment.
 */
export default function Login() {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState(null);
  const [pending, setPending] = useState(false);

  const onFinish = async (values) => {
    setPending(true);
    setError(null);
    try {
      const pair = await staffLogin(values);
      signIn(pair);
      navigate(location.state?.from?.pathname ?? '/products', { replace: true });
    } catch (failure) {
      // Deliberately not "no account with that email": login must not become an
      // oracle for which addresses are staff. The API takes the same care.
      setError(failure.message ?? 'Sign in failed.');
    } finally {
      setPending(false);
    }
  };

  return (
    <div className={styles.screen}>
      <Card className={styles.card}>
        <Typography.Title level={3}>Sign in</Typography.Title>
        <Typography.Paragraph type="secondary">
          Marvel back-office. Staff accounts only.
        </Typography.Paragraph>

        {error ? (
          <Alert type="error" title={error} className={styles.alert} showIcon />
        ) : null}

        <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
          <Form.Item
            label="Email"
            name="email"
            rules={[{ required: true, message: 'Email is required' }]}
          >
            <Input type="email" autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item
            label="Password"
            name="password"
            rules={[{ required: true, message: 'Password is required' }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={pending} block>
            Sign in
          </Button>
        </Form>
      </Card>
    </div>
  );
}

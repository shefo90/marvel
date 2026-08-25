import { Button, Result } from 'antd';
import { Link } from 'react-router-dom';

export default function NotFound() {
  return (
    <Result
      status="404"
      title="404"
      subTitle="No such screen."
      extra={
        <Link to="/products">
          <Button type="primary">Back to products</Button>
        </Link>
      }
    />
  );
}

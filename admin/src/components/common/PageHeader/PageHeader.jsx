import { Typography } from 'antd';

import styles from './PageHeader.module.scss';

/**
 * The one place a screen title and its actions are laid out, so every page
 * agrees on the spacing instead of each inventing its own.
 */
export default function PageHeader({ title, extra }) {
  return (
    <div className={styles.header}>
      <Typography.Title level={2} className={styles.title}>
        {title}
      </Typography.Title>
      {extra ? <div className={styles.actions}>{extra}</div> : null}
    </div>
  );
}

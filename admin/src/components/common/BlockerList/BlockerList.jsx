import { Alert } from 'antd';

/**
 * The structured blockers the API returns instead of a constraint violation.
 *
 * `POST /publish` answers 422 with a list of {code, message} rather than
 * letting ck_product_translations_published_requires_content surface as an
 * unreadable IntegrityError. Rendering that list as a list is the entire point
 * -- flattened into a toast it says nothing the operator can act on.
 */
export default function BlockerList({ blockers, title = 'Not ready to publish' }) {
  if (!blockers || blockers.length === 0) return null;

  return (
    <Alert
      type="warning"
      showIcon
      title={title}
      description={
        <ul>
          {blockers.map((blocker) => (
            <li key={blocker.code}>{blocker.message}</li>
          ))}
        </ul>
      }
    />
  );
}

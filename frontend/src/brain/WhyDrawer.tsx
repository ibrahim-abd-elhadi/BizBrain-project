import { Alert, Drawer, Segmented, Space, Spin, Tag, Typography } from "antd";
import { useState } from "react";
import { BRAIN_BASE } from "../api/client";
import type { Explanation, Language, RiskRow } from "../api/brainTypes";
import { useApiData } from "../api/useApiData";
import { textDirection } from "./language";
import { SyntheticTag } from "./shared";

/** Why? for one Risk and insights row (feature 005, US4): the risk level and the recommended order
 * in plain words, from the row's stored inputs. The template is marked "Plain version"; the
 * screen stays English, the text is right to left in Arabic (FR-001a). */
export function WhyDrawer({ row, onClose }: { row: RiskRow | null; onClose: () => void }) {
  const [language, setLanguage] = useState<Language>("en");
  const path = row ? `/explanations/${row.recommendation_id}?language=${language}` : null;
  const explanation = useApiData<Explanation>(path, BRAIN_BASE);
  const body = explanation.data && explanation.data.language === language && explanation.data.recommendation_id === row?.recommendation_id ? explanation.data : null;

  return (
    <Drawer
      open={row !== null}
      onClose={onClose}
      title={row ? `Why? ${row.product_name} (${row.product_id})` : "Why?"}
      size="large"
      destroyOnHidden
    >
      <Space orientation="vertical" size={16} className="full-width">
        <Space wrap>
          <SyntheticTag />
          <Segmented<Language>
            value={language}
            onChange={setLanguage}
            options={[
              { label: "English", value: "en" },
              { label: "Arabic", value: "ar" },
            ]}
          />
          {body?.source === "template" && <Tag>Plain version</Tag>}
        </Space>
        {explanation.error && <Alert type="error" showIcon title={explanation.error} />}
        {!body && !explanation.error && <Spin />}
        {body && (
          <Typography.Paragraph data-testid="why-text" className="generated-text" {...textDirection(language)}>
            {body.text}
          </Typography.Paragraph>
        )}
      </Space>
    </Drawer>
  );
}

import { Alert, Card, Empty, Segmented, Space, Typography } from "antd";
import { useState } from "react";
import { BRAIN_BASE } from "../api/client";
import type { Briefing, Language } from "../api/brainTypes";
import { useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { textDirection } from "./language";
import { SyntheticTag, cairoTime } from "./shared";

/** Brain → Briefing: the morning briefing written after the nightly run, in English with a switch
 * to Arabic shown right to left (feature 005, US3; FR-010, FR-011). The screen stays English. */
export function BriefingPage() {
  const briefing = useApiData<Briefing>("/briefing", BRAIN_BASE);
  const [language, setLanguage] = useState<Language>("en");
  const body = briefing.data;
  const text = body ? (language === "ar" ? body.text_ar : body.text_en) : null;

  return (
    <div className="page">
      <PageHeader
        title="Morning briefing"
        subtitle={
          <Space size={8} wrap>
            <SyntheticTag />
            <span>
              Written after the nightly run from that night's forecasts, risks, anomalies and recommendations.
              {body?.night ? ` Night of ${body.night}` : ""}
              {body?.run_finished_at ? `, run finished ${cairoTime(body.run_finished_at)}.` : ""}
            </span>
          </Space>
        }
      />
      <ErrorAlert error={briefing.error} />
      <Card loading={briefing.loading}>
        {body?.state === "none" && (
          <Empty description="No briefing yet: the first nightly run hasn't finished." />
        )}
        {body?.state === "offline" && (
          <Alert
            type="warning"
            showIcon
            title="Assistant offline"
            description="The language model couldn't be reached (or its text didn't pass the number check) when this night's briefing was due, so there is no briefing for it. The next nightly run writes one."
          />
        )}
        {body?.state === "written" && (
          <Space orientation="vertical" size={16} className="full-width">
            <Segmented<Language>
              value={language}
              onChange={setLanguage}
              options={[
                { label: "English", value: "en" },
                { label: "Arabic", value: "ar" },
              ]}
            />
            <Typography.Paragraph data-testid="briefing-text" className="generated-text" {...textDirection(language)}>
              {text}
            </Typography.Paragraph>
          </Space>
        )}
      </Card>
    </div>
  );
}

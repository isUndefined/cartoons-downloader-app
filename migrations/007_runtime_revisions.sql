CREATE TABLE runtime_revisions (
    section TEXT PRIMARY KEY,
    version INTEGER NOT NULL DEFAULT 0
);
INSERT INTO runtime_revisions(section) VALUES ('catalog'), ('jobs');

CREATE INDEX idx_jobs_video_latest ON download_jobs(video_id, id DESC);
CREATE INDEX idx_jobs_status_latest ON download_jobs(status, id DESC);
CREATE INDEX idx_videos_display_order ON videos(discovered_at DESC, score DESC, id DESC);

-- Revisions are transactional, including writes made outside the HTTP layer.
CREATE TRIGGER runtime_video_insert AFTER INSERT ON videos BEGIN
    UPDATE runtime_revisions SET version=version+1;
END;
CREATE TRIGGER runtime_video_delete AFTER DELETE ON videos BEGIN
    UPDATE runtime_revisions SET version=version+1;
END;
CREATE TRIGGER runtime_video_update AFTER UPDATE ON videos BEGIN
    UPDATE runtime_revisions SET version=version+1 WHERE section='catalog';
    UPDATE runtime_revisions SET version=version+1 WHERE section='jobs'
        AND (OLD.title IS NOT NEW.title OR OLD.youtube_id IS NOT NEW.youtube_id
             OR OLD.thumbnail_url IS NOT NEW.thumbnail_url OR OLD.channel_name IS NOT NEW.channel_name);
END;
CREATE TRIGGER runtime_job_insert AFTER INSERT ON download_jobs BEGIN
    UPDATE runtime_revisions SET version=version+1;
END;
CREATE TRIGGER runtime_job_delete AFTER DELETE ON download_jobs BEGIN
    UPDATE runtime_revisions SET version=version+1;
END;
CREATE TRIGGER runtime_job_update AFTER UPDATE ON download_jobs BEGIN
    UPDATE runtime_revisions SET version=version+1 WHERE section='jobs';
    UPDATE runtime_revisions SET version=version+1 WHERE section='catalog'
        AND (OLD.video_id IS NOT NEW.video_id OR OLD.status IS NOT NEW.status
             OR OLD.requested_quality IS NOT NEW.requested_quality
             OR OLD.actual_quality IS NOT NEW.actual_quality OR OLD.target_type IS NOT NEW.target_type);
END;
